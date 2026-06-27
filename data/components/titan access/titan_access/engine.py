# -*- coding: utf-8 -*-
"""Titan Access — orchestrator.

Python port of the C# ``ScreenReaderEngine`` (singleton orchestrator). It owns a
dedicated worker thread that runs a Win32 message pump — required both by the
low-level keyboard hook (``WH_KEYBOARD_LL``) and by the UI Automation COM event
callbacks. Everything the screen reader does is wired here; the heavy lifting
lives in the subsystem modules, which are imported defensively so a missing or
broken module degrades gracefully instead of taking the whole reader down.

This module is the integration contract: the subsystem modules implement exactly
the constructor / method signatures used below.

Engine surface used by subsystem modules (see method docstrings):
    engine.settings           -> SettingsStore
    engine.speech             -> SpeechAdapter (SpeechLike)
    engine.sound              -> SoundManager (SoundLike)
    engine.provider           -> UIAProvider (AccessibilityProviderLike)
    engine.current_object     -> Optional[AccessibleObject]
    engine.speak(text, obj=None, interrupt=True, pitch_offset=0)
    engine.speak_segments(segments)
    engine.play(sound_name, obj=None)
    engine.announce_object(obj, for_navigation=False, play_cursor=True)
    engine.refresh_current_scope(delay_ms=0)

Keyboard callbacks the hook invokes (return True to swallow the key):
    engine.on_modifier_gesture(vk, key_name, ctrl, alt, shift) -> bool
    engine.on_plain_key(vk, key_name, ctrl, alt, shift) -> bool
    engine.on_char_typed(ch) -> None
    engine.on_word_typed(word) -> None
    engine.on_toggle_key(kind, is_on) -> None      # kind: 'caps'|'num'|'scroll'
"""

import ctypes
import os
import threading
import time
from typing import List, Optional, Tuple

from titan_access import localization as loc
from titan_access.localization import L
from titan_access.settings_store import (
    get_settings, AnnouncementMode, KeyboardEchoSetting,
)
from titan_access.contracts import (
    AccessibleObject, pan_for_object, elevation_for_object,
    SND_SR_ON, SND_SR_OFF, SND_CURSOR, SND_SR_CURSOR_ITEM, SND_LIST_ITEM,
    SND_WINDOW, SND_ERROR, SND_VSCREEN_ON, SND_VSCREEN_OFF,
)

# Pitches for the three-part announcement (name / type / state), like titan_talk.
NAME_PITCH = 0
ROLE_PITCH = -4
STATE_PITCH = 4

# Roles that get the "cursor" (interactive) cue; everything else that is not a
# list/tree item gets "cursor_static". Mirrors the C# IsInteractiveElement split.
_INTERACTIVE_ROLES = {
    "button", "split_button", "checkbox", "radio", "combobox", "edit",
    "password", "slider", "spinner", "link", "menuitem", "menubar", "tab",
    "scrollbar", "tabcontrol",
}
_LIST_ITEM_ROLES = {"listitem", "treeitem", "griditem"}


def _try(import_callable, label):
    try:
        return import_callable()
    except Exception as e:  # pragma: no cover - defensive during parallel dev
        print(f"[TitanAccess] optional subsystem '{label}' unavailable: {e}")
        return None


class TitanAccessEngine:
    """Central screen-reader orchestrator (singleton via :data:`instance`)."""

    instance: "Optional[TitanAccessEngine]" = None

    def __init__(self):
        self.settings = get_settings()
        loc.sync_with_tce()

        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0
        self._ready = threading.Event()

        self.current_object: Optional[AccessibleObject] = None
        self._last_focus_key = None
        self._was_in_tce = None        # None until the first focus establishes it

        # Subsystems (populated in _build_subsystems on the worker thread).
        self.speech = None
        self.sound = None
        self.provider = None
        self.keyboard = None
        self.gestures = None
        self.browse = None
        self.object_nav = None
        self.editable = None
        self.app_modules = None
        self.important_places = None

        TitanAccessEngine.__dict__  # noqa - keep linters calm

    # ==================================================================== #
    # Lifecycle
    # ==================================================================== #
    def start(self) -> bool:
        if self.running:
            return True
        self.running = True
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="TitanAccessEngine",
                                        daemon=True)
        self._thread.start()
        # Wait briefly for subsystems to come up so the toggle announcement is sane.
        self._ready.wait(timeout=5.0)
        TitanAccessEngine.instance = self
        return True

    def stop(self):
        if not self.running:
            return
        self.running = False
        # Announce shutdown before tearing down speech.
        try:
            if AnnouncementMode.plays(self.settings.startup_announcement):
                self.play(SND_SR_OFF)
            if AnnouncementMode.speaks(self.settings.startup_announcement):
                self.speak(L("engine.closing"))
                time.sleep(0.4)
        except Exception:
            pass
        # Post WM_QUIT to the worker thread's message loop.
        if self._thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        TitanAccessEngine.instance = None

    def _run(self):
        """Worker thread: build subsystems then pump Win32 messages."""
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        # COM must be initialised on this thread for UIA.
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
        except Exception:
            pass

        self._build_subsystems()
        self._ready.set()

        # Startup announcement.
        try:
            if AnnouncementMode.plays(self.settings.startup_announcement):
                self.play(SND_SR_ON)
            if AnnouncementMode.speaks(self.settings.startup_announcement):
                msg = self.settings.welcome_message or L("app.welcome")
                self.speak(msg)
        except Exception as e:
            print(f"[TitanAccess] startup announcement error: {e}")

        # Announce the element that already has focus.
        try:
            if self.provider is not None:
                obj = self.provider.get_focused_object()
                if obj is not None:
                    self.announce_object(obj, play_cursor=False)
        except Exception:
            pass

        # Win32 message loop (drives WH_KEYBOARD_LL + UIA COM callbacks).
        msg = ctypes.wintypes.MSG() if hasattr(ctypes, "wintypes") else None
        try:
            import ctypes.wintypes as wt
            msg = wt.MSG()
            user32 = ctypes.windll.user32
            while self.running:
                r = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if r == 0 or r == -1:  # WM_QUIT or error
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            print(f"[TitanAccess] message loop error: {e}")
        finally:
            self._teardown_subsystems()
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass

    def _build_subsystems(self):
        from titan_access.settings_store import get_settings as _gs
        self.settings = _gs()

        # --- audio -------------------------------------------------------- #
        def _mk_speech():
            from titan_access.speech_adapter import SpeechAdapter
            sp = SpeechAdapter(self.settings)
            return sp
        self.speech = _try(_mk_speech, "speech_adapter")

        def _mk_sound():
            import os
            from titan_access.sound_manager import SoundManager
            sfx = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sfx")
            return SoundManager(sfx)
        self.sound = _try(_mk_sound, "sound_manager")

        # --- accessibility provider -------------------------------------- #
        def _mk_provider():
            from titan_access.uia_focus import UIAProvider
            p = UIAProvider()
            p.add_focus_listener(self.on_focus)
            p.start()
            return p
        self.provider = _try(_mk_provider, "uia_focus")

        # --- input ------------------------------------------------------- #
        self.object_nav = _try(lambda: __import__(
            "titan_access.object_nav", fromlist=["ObjectNavigator"]
        ).ObjectNavigator(self), "object_nav")
        self.editable = _try(lambda: __import__(
            "titan_access.editable_text", fromlist=["EditableTextHandler"]
        ).EditableTextHandler(self), "editable_text")
        self.gestures = _try(lambda: __import__(
            "titan_access.gestures", fromlist=["GestureManager"]
        ).GestureManager(self), "gestures")
        self.browse = _try(lambda: __import__(
            "titan_access.browse_mode", fromlist=["BrowseModeHandler"]
        ).BrowseModeHandler(self), "browse_mode")
        self.app_modules = _try(lambda: __import__(
            "titan_access.app_modules.manager", fromlist=["AppModuleManager"]
        ).AppModuleManager(self), "app_modules")
        self.important_places = _try(lambda: __import__(
            "titan_access.important_places", fromlist=["ImportantPlacesManager"]
        ).ImportantPlacesManager(self), "important_places")

        # Keyboard hook last — it starts feeding events immediately.
        def _mk_kbd():
            from titan_access.keyboard_hook import KeyboardHook
            kh = KeyboardHook(self)
            kh.start()
            return kh
        self.keyboard = _try(_mk_kbd, "keyboard_hook")

        if self.gestures is not None:
            try:
                self._register_default_gestures()
            except Exception as e:
                print(f"[TitanAccess] gesture registration error: {e}")

    def _teardown_subsystems(self):
        for name in ("keyboard", "provider"):
            obj = getattr(self, name, None)
            if obj is not None and hasattr(obj, "stop"):
                try:
                    obj.stop()
                except Exception:
                    pass

    # ==================================================================== #
    # "Mute outside TCE" gating
    # ==================================================================== #
    def _foreground_pid(self) -> int:
        try:
            u = ctypes.windll.user32
            hwnd = u.GetForegroundWindow()
            if not hwnd:
                return 0
            pid = ctypes.wintypes.DWORD() if hasattr(ctypes, "wintypes") else None
            import ctypes.wintypes as wt
            pid = wt.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return int(pid.value)
        except Exception:
            return 0

    def _is_tce_foreground(self) -> bool:
        """True when the foreground window belongs to the TCE environment.

        That means our own process (the launcher, and the in-process settings,
        component views and applets that share our PID) OR a descendant process
        we launched (TCE applications started as child processes). Cached briefly
        because focus events are frequent.
        """
        now = time.time()
        cache = getattr(self, "_tce_fg_cache", None)
        if cache is not None and (now - cache[0]) < 0.3:
            return cache[1]
        result = self._compute_is_tce_foreground()
        self._tce_fg_cache = (now, result)
        return result

    def _compute_is_tce_foreground(self) -> bool:
        return self._pid_is_tce(self._foreground_pid())

    def _pid_is_tce(self, pid) -> bool:
        """True if *pid* is the launcher process or a process it spawned."""
        if not pid:
            return False
        own = os.getpid()
        if pid == own:
            return True
        # Walk the process's ancestor chain; if the launcher (our PID) is an
        # ancestor, this is a TCE-launched application.
        try:
            import psutil
            proc = psutil.Process(pid)
            for _ in range(12):
                parent = proc.parent()
                if parent is None:
                    break
                if parent.pid == own:
                    return True
                proc = parent
        except Exception:
            # Without psutil we can only recognise our own process windows.
            pass
        return False

    def _muted_for_foreground(self) -> bool:
        """True when ambient announcements should be suppressed right now."""
        try:
            if not self.settings.mute_outside_tce:
                return False
            return not self._is_tce_foreground()
        except Exception:
            return False

    # ==================================================================== #
    # Output convenience
    # ==================================================================== #
    def _pan_for_speech(self, obj) -> float:
        """Speech is centered normally; panned to the element only in virtual screen."""
        if obj is not None and self.settings.virtual_screen:
            return pan_for_object(obj)
        return 0.0

    def speak(self, text, obj=None, interrupt=True, pitch_offset=0):
        if not text or self.speech is None:
            return
        try:
            self.speech.speak_async(text, position=self._pan_for_speech(obj),
                                    interrupt=interrupt, pitch_offset=pitch_offset)
        except Exception as e:
            print(f"[TitanAccess] speak error: {e}")

    def speak_segments(self, segments):
        """Speak ``(text, pitch_offset)`` parts sequentially at their own pitch."""
        if self.speech is None:
            return
        # Resolve pan once from the current object (virtual screen only).
        pan = self._pan_for_speech(self.current_object)
        full = [(t, p, pan) for (t, p) in segments if t]
        try:
            if hasattr(self.speech, "speak_segments"):
                self.speech.speak_segments(full)
            else:  # fallback: join into one line
                self.speak(" ".join(t for t, _p, _pan in full))
        except Exception as e:
            print(f"[TitanAccess] speak_segments error: {e}")

    def play(self, sound_name, obj=None):
        if self.sound is None or not sound_name:
            return
        try:
            self.sound.play_positioned(sound_name, obj)
        except Exception as e:
            print(f"[TitanAccess] play error: {e}")

    def _play_element_cue(self, obj, for_navigation):
        """Play the per-element cue, faithfully ported from C# AnnounceElement.

        Sounds are always stereo-panned to the element (independent of the
        virtual-screen setting). List/tree items use ``listitem.ogg`` pitched by
        their vertical position in the set (top = high, bottom = low) plus an
        edge cue at the first/last item; buttons and other interactive controls
        use ``cursor.ogg``; static controls use ``cursor_static.ogg``; panes and
        groups reached by object navigation use ``caninteract.ogg``.
        """
        if self.sound is None or obj is None:
            return
        pan = pan_for_object(obj)
        role = obj.role
        try:
            if role in _LIST_ITEM_ROLES:
                pos = 0.0
                if obj.size_of_set and obj.size_of_set > 1 and obj.pos_in_set:
                    pos = (obj.pos_in_set - 1) / float(obj.size_of_set - 1)
                self.sound.play_list_item(pos, pan)
                if (obj.pos_in_set and obj.size_of_set
                        and (obj.pos_in_set == 1 or obj.pos_in_set == obj.size_of_set)):
                    self.sound.play_edge(pan)
            elif for_navigation and role in ("pane", "group"):
                self.sound.play_can_interact(pan)
            elif role == "button" or role in _INTERACTIVE_ROLES:
                self.sound.play_cursor(pan)
            else:
                self.sound.play_cursor_static(pan)
        except Exception as e:
            print(f"[TitanAccess] element cue error: {e}")

    # ==================================================================== #
    # Focus / announcement
    # ==================================================================== #
    def on_focus(self, obj: AccessibleObject):
        """UIA focus listener. Marshalled onto our thread by the provider."""
        if obj is None:
            return
        self.current_object = obj
        # Enter/leave TCE environment cue (port of the process-change branch in
        # the C# OnFocusChanged).
        self._handle_tce_transition(obj)
        # Let the active app module customise / suppress.
        try:
            if self.app_modules is not None:
                self.app_modules.on_gain_focus(obj)
        except Exception:
            pass
        self.announce_object(obj)

    def _handle_tce_transition(self, obj):
        """Play enter_TCE / leave_TCE when focus crosses the TCE boundary."""
        try:
            pid = obj.process_id or self._foreground_pid()
            is_tce = self._pid_is_tce(pid)
            was = self._was_in_tce
            if was is None:
                self._was_in_tce = is_tce
                return
            if is_tce and not was:
                if self.settings.tce_entry_sound and self.sound is not None:
                    try:
                        self.sound.play_enter_tce()
                    except Exception:
                        pass
                self.speak("Titan", interrupt=False)
            elif (not is_tce) and was:
                if self.settings.tce_entry_sound and self.sound is not None:
                    try:
                        self.sound.play_leave_tce()
                    except Exception:
                        pass
                if not self.settings.mute_outside_tce:
                    self.speak(L("engine.unsupportedApp"), interrupt=False)
            self._was_in_tce = is_tce
        except Exception as e:
            print(f"[TitanAccess] tce transition error: {e}")

    def announce_object(self, obj: AccessibleObject, for_navigation=False,
                        play_cursor=True):
        """Speak an element (3-part pitched announcement) and play its cursor sound."""
        if obj is None:
            self.speak(L("engine.noCurrentElement"))
            return
        self.current_object = obj
        # "Mute outside TCE": suppress ambient focus announcements when the
        # foreground is not part of the TCE environment (its apps/components/
        # settings still count as TCE and are NOT muted).
        if self._muted_for_foreground():
            return
        if play_cursor:
            self._play_element_cue(obj, for_navigation)
        try:
            from titan_access import accessible
            segments = accessible.describe(obj, self.settings,
                                           for_navigation=for_navigation)
        except Exception as e:
            print(f"[TitanAccess] describe error: {e}")
            segments = [(obj.name or loc.role_label(obj.role), NAME_PITCH)]
        # If the active TTS path has no pitch control, flatten to one line.
        if self.speech is not None and not getattr(self.speech, "supports_pitch", True):
            self.speak(" ".join(t for t, _p in segments if t), obj=obj)
        else:
            self.speak_segments(segments)

    def refresh_current_scope(self, delay_ms=0):
        """Re-read focus after an action that may have changed the UI."""
        def _do():
            if delay_ms:
                time.sleep(delay_ms / 1000.0)
            try:
                if self.provider is not None:
                    obj = self.provider.get_focused_object()
                    if obj is not None:
                        self.on_focus(obj)
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()

    # ==================================================================== #
    # Keyboard callbacks (invoked by KeyboardHook)
    # ==================================================================== #
    def on_modifier_gesture(self, vk, key_name, ctrl, alt, shift) -> bool:
        if self.gestures is None:
            return False
        try:
            return bool(self.gestures.dispatch(key_name, vk, ctrl, alt, shift))
        except Exception as e:
            print(f"[TitanAccess] gesture dispatch error: {e}")
            return False

    def on_plain_key(self, vk, key_name, ctrl, alt, shift) -> bool:
        # Browse mode quick-nav / arrows take precedence when active.
        try:
            if self.browse is not None and self.browse.is_active:
                if self.browse.handle_key(vk, key_name, ctrl, alt, shift):
                    return True
        except Exception:
            pass
        return False

    def on_char_typed(self, ch):
        if self._muted_for_foreground():
            return
        if not KeyboardEchoSetting.echo_chars(self.settings.keyboard_echo):
            return
        try:
            self.speak(loc.character_announcement(ch, use_phonetic=False),
                       interrupt=True)
        except Exception:
            pass

    def on_word_typed(self, word):
        if self._muted_for_foreground():
            return
        if not KeyboardEchoSetting.echo_words(self.settings.keyboard_echo):
            return
        if word:
            self.speak(word, interrupt=True)

    def on_toggle_key(self, kind, is_on):
        if self._muted_for_foreground():
            return
        mode = self.settings.get("Verbosity", "ToggleKeysMode")
        if AnnouncementMode.plays(AnnouncementMode.normalize(mode)):
            self.play("keyon.ogg" if is_on else "keyoff.ogg")
        if AnnouncementMode.speaks(AnnouncementMode.normalize(mode)):
            key = {
                ("caps", True): "toggle.capsLockOn", ("caps", False): "toggle.capsLockOff",
                ("scroll", True): "toggle.scrollLockOn", ("scroll", False): "toggle.scrollLockOff",
                ("num", True): "toggle.numpadNumeric", ("num", False): "toggle.numpadTceCursor",
            }.get((kind, is_on))
            if key:
                self.speak(L(key))

    # ==================================================================== #
    # Gesture actions (registered with GestureManager)
    # ==================================================================== #
    def _register_default_gestures(self):
        g = self.gestures
        # (action_id, default key spec, handler)
        g.register("readCurrentElement", "numpad5", self.action_read_current_element)
        g.register("readElementType", "t", self.action_read_element_type)
        g.register("stopSpeaking", "control", self.action_stop_speaking)
        g.register("toggleBrowseMode", "space", self.action_toggle_browse_mode)
        g.register("toggleVirtualScreen", "v", self.action_toggle_virtual_screen)
        g.register("readTime", "f12", self.action_read_time)
        g.register("readDate", "shift+f12", self.action_read_date)
        g.register("readWindowTitle", "t", self.action_read_window_title)
        g.register("cycleKeyEcho", "s", self.action_cycle_key_echo)

        # Object navigation (NumPad, with the reader modifier held) — wired only
        # when the object navigator subsystem is available.
        if self.object_nav is not None:
            for key, direction in (("numpad4", "prev"), ("numpad6", "next"),
                                   ("numpad8", "parent"), ("numpad2", "child"),
                                   ("numpad5", "current"), ("numpadenter", "activate")):
                g.register(f"objnav_{direction}", key,
                           (lambda d: (lambda *a: self._object_nav(d)))(direction))

    def _object_nav(self, direction):
        if self.object_nav is None:
            return False
        try:
            return bool(self.object_nav.navigate(direction))
        except Exception as e:
            print(f"[TitanAccess] object nav error: {e}")
            return False

    def action_read_current_element(self, *a):
        self.announce_object(self.current_object, play_cursor=False)
        return True

    def action_read_element_type(self, *a):
        if self.current_object is None:
            self.speak(L("element.none"))
        else:
            self.speak(L("engine.elementType", loc.role_label(self.current_object.role)))
        return True

    def action_stop_speaking(self, *a):
        if self.speech is not None:
            self.speech.stop()
        return True

    def action_toggle_browse_mode(self, *a):
        if self.browse is not None:
            try:
                self.browse.toggle_pass_through()
                return True
            except Exception:
                pass
        return False

    def action_toggle_virtual_screen(self, *a):
        new = not self.settings.virtual_screen
        self.settings.virtual_screen = new
        self.settings.save()
        self.play(SND_VSCREEN_ON if new else SND_VSCREEN_OFF)
        self.speak(L("vscreen.enabled" if new else "vscreen.disabled"))
        return True

    def action_read_time(self, *a):
        self.speak(time.strftime("%H:%M"))
        return True

    def action_read_date(self, *a):
        self.speak(time.strftime("%x"))
        return True

    def action_read_window_title(self, *a):
        try:
            u = ctypes.windll.user32
            hwnd = u.GetForegroundWindow()
            n = u.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            self.speak(buf.value or L("engine.windowNotFound"))
        except Exception:
            self.speak(L("engine.windowNotFound"))
        return True

    def action_cycle_key_echo(self, *a):
        order = [KeyboardEchoSetting.CHARACTERS, KeyboardEchoSetting.WORDS,
                 KeyboardEchoSetting.CHARACTERS_AND_WORDS, KeyboardEchoSetting.NONE]
        cur = self.settings.keyboard_echo
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else order[0]
        self.settings.keyboard_echo = nxt
        self.settings.save()
        label = {
            KeyboardEchoSetting.CHARACTERS: "keyEcho.characters",
            KeyboardEchoSetting.WORDS: "keyEcho.words",
            KeyboardEchoSetting.CHARACTERS_AND_WORDS: "keyEcho.wordsAndChars",
            KeyboardEchoSetting.NONE: "keyEcho.none",
        }.get(nxt, "keyEcho.unknown")
        self.speak(L("engine.keyEcho", L(label)))
        return True


# --------------------------------------------------------------------------- #
# Module-level singleton helpers
# --------------------------------------------------------------------------- #
def get_engine() -> TitanAccessEngine:
    if TitanAccessEngine.instance is None:
        TitanAccessEngine.instance = TitanAccessEngine()
    return TitanAccessEngine.instance


def is_running() -> bool:
    return TitanAccessEngine.instance is not None and TitanAccessEngine.instance.running
