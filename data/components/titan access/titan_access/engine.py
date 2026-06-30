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
    SND_CONTROLLER_INIT, SND_CONTROLLER_UNINIT,
)

# Pitches for the three-part announcement (name / type / state), like titan_talk.
NAME_PITCH = 0
ROLE_PITCH = -4
STATE_PITCH = 4

# Custom thread message used to marshal a callable onto the worker thread's
# Win32 message loop (WM_APP + 1). Posted with hwnd == NULL via PostThreadMessage.
WM_TA_INVOKE = 0x8000 + 1

# Roles that get the "cursor" (interactive) cue; everything else that is not a
# list/tree item gets "cursor_static". Mirrors the C# IsInteractiveElement split.
_INTERACTIVE_ROLES = {
    "button", "split_button", "checkbox", "radio", "combobox", "edit",
    "password", "slider", "spinner", "link", "menuitem", "menubar", "tab",
    "scrollbar", "tabcontrol",
}
_LIST_ITEM_ROLES = {"listitem", "treeitem", "griditem"}
# Roles whose focus enables edit-field caret tracking (arrow keys read text).
_EDIT_ROLES = {"edit", "password", "document", "combobox"}
# UIA FrameworkId values that mark a "document" as WEB content (Chromium / Gecko
# / WebView). A web document is driven by browse mode, NEVER by edit-caret
# tracking -- otherwise arrows would read the page linearly instead of
# navigating it. (A Word / Notepad document has a non-web framework id and keeps
# caret tracking.)
_WEB_DOC_FRAMEWORKS = {"chrome", "gecko", "webview", "edge", "blink"}
# Pure-container roles that often receive a transient focus event right before
# a real control inside them does (e.g. a dialog window focuses, then its OK
# button). Announcing the container immediately would consume the "newly entered
# dialog" context, so the follow-up control read loses the dialog's message. We
# defer these briefly; a real control focusing next supersedes them.
_CONTAINER_FOCUS_ROLES = {"window", "dialog", "pane", "group"}


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
        self._last_focus_time = 0.0
        self._had_focus = False        # False until the first focus is processed
                                       # (lets the TCE app module skip a startup cue)
        self._in_controller_app = False  # focus is in an NVDA-controller client
        self._announce_token = 0         # coalesces rapid focus bursts

        # Cross-thread "run this on the worker (COM-initialised) thread" queue.
        # Used so TextPattern caret reads happen on the same apartment that owns
        # the UIA elements (no cross-apartment marshalling -> no ~500 ms stall).
        self._invoke_lock = threading.Lock()
        self._invoke_queue: List = []

        # Dedicated background worker (NOT the keyboard-hook thread!). Blocking
        # work -- TextPattern caret reads, speech.stop() -- runs here so it can
        # never stall the global WH_KEYBOARD_LL hook (which froze the whole app).
        self._bg_lock = threading.Lock()
        self._bg_event = threading.Event()
        self._bg_read = None        # latest pending caret read (latest wins)
        self._bg_stop = False       # a stop-speech request is pending
        self._bg_alive = False
        self._bg_thread: Optional[threading.Thread] = None

        # Host-app announcement hooks (TCE pushes these for widgets whose meaning
        # UIA cannot convey -- the virtual tab bar, wx.CheckListBox check state).
        self._override_until = 0.0       # suppress our next auto announce until
        self._state_suffix = None        # (text, expiry) appended to next announce
        self._role_label_override = None  # (text, expiry) replaces next role label
        # HWND of the throwaway frame that hosts our own popup menu (Insert+C).
        # Its focus must NOT be announced ("panel"/"window") -- but the popup's
        # menu / menu items (different role) still are. 0 = no menu host active.
        self._menu_host_hwnd = 0
        # Host-declared kind for the NEXT dialog ("question"/"information"/...),
        # used when the reader cannot detect the icon (e.g. a generic wx dialog).
        # (kind, expiry); consumed by the context presenter. See host_bridge.
        self._dialog_kind_override = None

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
        self.menu_tracker = None
        self.dial = None
        self.context = None
        self.nvda_ctl = None

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

        # Tell Windows a screen reader is active. Chromium (Chrome/Edge/WebView2),
        # Firefox/Gecko and Office only build their accessibility tree when an AT
        # is detected; without this flag a web document exposes no children and
        # browse mode has nothing to read.
        self._set_screen_reader_flag(True)

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
                # Callables posted from other threads run here, on the COM
                # apartment that owns the UIA elements (see post_to_worker).
                if msg.message == WM_TA_INVOKE and not msg.hwnd:
                    self._drain_invokes()
                    continue
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            print(f"[TitanAccess] message loop error: {e}")
        finally:
            self._teardown_subsystems()
            self._set_screen_reader_flag(False)
            try:
                ctypes.windll.ole32.CoUninitialize()
            except Exception:
                pass

    @staticmethod
    def _set_screen_reader_flag(on):
        """Set/clear the system SPI_SETSCREENREADER flag so applications that gate
        their accessibility tree on AT presence (Chromium, Firefox, Office) build
        and expose it. Best-effort; never fatal."""
        try:
            SPI_SETSCREENREADER = 0x0047
            SPIF_SENDCHANGE = 0x0002
            ctypes.windll.user32.SystemParametersInfoW(
                SPI_SETSCREENREADER, 1 if on else 0, None, SPIF_SENDCHANGE)
        except Exception as e:
            print(f"[TitanAccess] screen reader flag error: {e}")

    def _build_subsystems(self):
        from titan_access.settings_store import get_settings as _gs
        self.settings = _gs()

        # Background worker first: caret reads / stop-speech offload to it so the
        # keyboard-hook thread never blocks.
        self._start_bg_worker()

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
        # UIA primary + MSAA fallback, auto-switching per focus (NVDA-style).
        # Falls back to the bare UIA provider if the manager cannot be built.
        def _mk_provider():
            from titan_access.provider_manager import ProviderManager
            p = ProviderManager()
            p.add_focus_listener(self.on_focus)
            p.start()
            return p
        self.provider = _try(_mk_provider, "provider_manager")
        if self.provider is None:
            def _mk_uia():
                from titan_access.uia_focus import UIAProvider
                p = UIAProvider()
                p.add_focus_listener(self.on_focus)
                p.start()
                return p
            self.provider = _try(_mk_uia, "uia_focus")

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
        self.menu_tracker = _try(lambda: __import__(
            "titan_access.menu_tracker", fromlist=["MenuTracker"]
        ).MenuTracker(self), "menu_tracker")
        self.dial = _try(lambda: __import__(
            "titan_access.dial", fromlist=["DialManager"]
        ).DialManager(self), "dial")
        self.context = _try(lambda: __import__(
            "titan_access.context_presenter", fromlist=["ContextPresenter"]
        ).ContextPresenter(self), "context_presenter")

        # NVDA controller server: lets external apps (and accessible_output3's
        # NVDA backend) speak through Titan Access. Needs the native helper DLL;
        # degrades to a no-op when it is not present.
        self.nvda_ctl = _try(lambda: __import__(
            "titan_access.nvda_controller_server", fromlist=["NvdaControllerServer"]
        ).NvdaControllerServer(self).start(), "nvda_controller_server")

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
        self._stop_bg_worker()
        for name in ("keyboard", "provider", "nvda_ctl"):
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
    # Worker-thread invocation (run COM work on the apartment that owns it)
    # ==================================================================== #
    def post_to_worker(self, fn):
        """Queue ``fn`` to run on the engine worker thread's message loop.

        The worker thread is the COM apartment that created the UIA provider and
        owns the focused elements, so reading TextPattern / properties there is
        in-apartment and fast. Calling the same work from an arbitrary thread
        marshals every COM access across apartments, which is what made arrow
        navigation in edit fields lag by hundreds of milliseconds."""
        with self._invoke_lock:
            self._invoke_queue.append(fn)
        if self._thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(
                    self._thread_id, WM_TA_INVOKE, 0, 0)
            except Exception as e:
                print(f"[TitanAccess] post_to_worker error: {e}")

    def _drain_invokes(self):
        while True:
            with self._invoke_lock:
                if not self._invoke_queue:
                    return
                fn = self._invoke_queue.pop(0)
            try:
                fn()
            except Exception as e:
                print(f"[TitanAccess] worker invoke error: {e}")

    # ------------------------------------------------------------------ #
    # Background worker (off the keyboard-hook thread)
    # ------------------------------------------------------------------ #
    def _start_bg_worker(self):
        if self._bg_alive:
            return
        self._bg_alive = True
        self._bg_thread = threading.Thread(
            target=self._bg_loop, name="TitanAccessBg", daemon=True)
        self._bg_thread.start()

    def _stop_bg_worker(self):
        self._bg_alive = False
        self._bg_event.set()

    def _bg_loop(self):
        # COM (MTA) so this thread can make UIA calls itself. UIA elements are
        # agile, so reading the focused element here does not need the apartment
        # that created it. MTA needs no message pump for outgoing calls.
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x0)  # COINIT_MULTITHREADED
        except Exception:
            pass
        while self._bg_alive:
            self._bg_event.wait()
            self._bg_event.clear()
            if not self._bg_alive:
                break
            if self._bg_stop:
                self._bg_stop = False
                try:
                    if self.speech is not None:
                        self.speech.stop()
                except Exception:
                    pass
            with self._bg_lock:
                fn = self._bg_read
                self._bg_read = None
            if fn is not None:
                try:
                    fn()
                except Exception as e:
                    print(f"[TitanAccess] bg read error: {e}")
        try:
            ctypes.windll.ole32.CoUninitialize()
        except Exception:
            pass

    def submit_read(self, fn):
        """Queue a (possibly blocking) caret read on the background thread.
        Only the latest read is kept, so holding an arrow key never backs up."""
        with self._bg_lock:
            self._bg_read = fn
        self._bg_event.set()

    def request_stop_speech(self):
        """Ask the background thread to stop speech (safe from the hook thread)."""
        self._bg_stop = True
        self._bg_event.set()

    # ==================================================================== #
    # Host-app announcement hooks (called by TCE through host_bridge)
    # ==================================================================== #
    def announce_override(self, text, interrupt=True, pitch_offset=0):
        """Speak an exact phrase supplied by the host application for a control
        whose meaning UIA cannot convey (the virtual tab bar). Suppresses our own
        next focus announcement for a brief window so the two never double up.

        ``pitch_offset`` lets the host ask for a non-neutral tone -- e.g. the
        launcher announces a region name ("Application list") a little lower so
        it is clearly a container, not a list row."""
        if not text:
            return
        self._override_until = time.time() + 0.7
        self.speak(text, interrupt=interrupt, pitch_offset=pitch_offset)

    def announce_segments(self, segments, interrupt=True):
        """Speak host-supplied ``(text, pitch_offset)`` parts as one pitched
        utterance and suppress our own next focus announcement.

        Used when the host wants to mix tones in a single phrase -- e.g. during
        a tab-bar drag: the view name a little higher, then "at position N" at
        the neutral pitch (replacing the reader's plain "selected, N of M")."""
        parts = [(t, p) for (t, p) in (segments or []) if t]
        if not parts:
            return
        self._override_until = time.time() + 0.7
        # ``speak_segments`` interrupts whatever is playing with its first
        # segment, so an explicit stop is unnecessary here.
        self.speak_segments(parts)

    def set_state_suffix(self, text):
        """Queue a state word (e.g. "checked") to append to our next focus
        announcement, for host widgets whose state is invisible to UIA
        (wx.CheckListBox). Consumed by the next :meth:`announce_object`."""
        if text:
            self._state_suffix = (text, time.time() + 0.7)

    def set_role_label(self, text):
        """Queue a control-type label that REPLACES the role word in our next
        focus announcement. For host widgets whose UIA role is too generic --
        e.g. a status-bar slot is just a "list item" to UIA, but the launcher
        wants it read as "status bar item". Consumed by the next
        :meth:`announce_object`."""
        if text:
            self._role_label_override = (text, time.time() + 0.7)

    def set_dialog_kind(self, kind):
        """Declare the kind of the NEXT dialog ("question" / "information" /
        "warning" / "error"), for dialogs whose icon the reader cannot detect
        (e.g. a skinned / generic wx dialog). The context presenter prefers this
        over icon detection, so a host-declared dialog is classified reliably
        regardless of the active skin. Consumed by the next dialog announcement."""
        if kind:
            self._dialog_kind_override = (kind, time.time() + 5.0)

    def consume_dialog_kind(self):
        o = self._dialog_kind_override
        if o and o[1] > time.time():
            self._dialog_kind_override = None
            return o[0]
        self._dialog_kind_override = None
        return None

    def _consume_override(self) -> bool:
        if self._override_until > time.time():
            self._override_until = 0.0
            return True
        return False

    def _consume_state_suffix(self):
        s = self._state_suffix
        if s and s[1] > time.time():
            self._state_suffix = None
            return s[0]
        self._state_suffix = None
        return None

    def _consume_role_label(self):
        r = self._role_label_override
        if r and r[1] > time.time():
            self._role_label_override = None
            return r[0]
        self._role_label_override = None
        return None

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
        # Inside the Titan environment's own windows (the launcher, its settings,
        # component views and applets share our PID) the TCE shell already plays
        # its own navigation sounds; our cursor cues on top of those just clutter,
        # so suppress them there. Speech is unaffected.
        if (obj.process_id or self._foreground_pid()) == os.getpid():
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
        # Swallow focus on our own popup-menu host frame (Insert+C). Without this
        # the empty hosting window is announced as "panel" / "window" right before
        # the menu opens. The popup's menu and menu items live in a different
        # window (role menu/menuitem) so they are still announced normally.
        if (self._menu_host_hwnd
                and getattr(obj, "hwnd", 0) == self._menu_host_hwnd
                and obj.role not in ("menu", "menuitem")):
            return
        self.current_object = obj
        # Auto browse/focus mode for web documents (NVDA-style). MUST run BEFORE
        # _update_edit_context: that method decides whether arrows do edit-caret
        # tracking or browse navigation based on browse.pass_through, so the mode
        # has to be updated for THIS focus first. Doing it after left the edit
        # context reading the PREVIOUS focus's mode -- so after tabbing through a
        # form field and back to page content, arrows stayed in caret-tracking
        # mode and browse navigation appeared dead.
        if self.browse is not None:
            try:
                self.browse.update_for_focus(obj)
            except Exception as e:
                print(f"[TitanAccess] browse update error: {e}")
        # Bind edit-field caret tracking to the newly focused control.
        self._update_edit_context(obj)
        # Enter/leave an app that drives us through the NVDA controller.
        self._handle_controller_transition(obj)
        # Menu bar / menu announcements take over when focus is in a menu.
        try:
            if self.menu_tracker is not None and self.menu_tracker.handle_focus(obj):
                return
        except Exception as e:
            print(f"[TitanAccess] menu tracker error: {e}")
        # Let the active app module customise / suppress.
        try:
            if self.app_modules is not None:
                self.app_modules.on_gain_focus(obj)
                # Mark the baseline established AFTER the first delegation, so the
                # TCE app module can tell a real boundary-cross from startup.
                self._had_focus = True
                if not self.app_modules.should_announce(obj):
                    return
        except Exception:
            pass
        self._announce_focus(obj)

    def _announce_focus(self, obj):
        """Announce a focus change, coalescing rapid bursts.

        A real control (button, edit, list item, ...) is announced immediately
        and cancels any pending container announcement. A pure container
        (dialog window / pane / group) is deferred briefly: if a control inside
        it focuses next, that control wins and carries the container context
        (so e.g. a dialog's message is read with its OK button, not lost to a
        transient window-focus event that already "used up" the context)."""
        # Drop a duplicate focus burst for the same element (some controls fire
        # the focus event twice; the second carries no new context and would
        # otherwise cut off the first announcement before its dialog/group
        # context is spoken).
        key = (obj.role, obj.name, obj.bounds, obj.automation_id)
        now = time.time()
        if key == self._last_focus_key and (now - self._last_focus_time) < 0.35:
            return
        self._last_focus_key = key
        self._last_focus_time = now

        self._announce_token += 1
        tok = self._announce_token
        if obj.role in _CONTAINER_FOCUS_ROLES:
            def _fire():
                if tok == self._announce_token:
                    self.announce_object(obj)
            threading.Timer(0.12, _fire).start()
        else:
            self.announce_object(obj)

    def _update_edit_context(self, obj):
        """Tell the keyboard hook and editable handler whether focus is now in
        an editable control, so arrow movements read the caret."""
        is_edit = obj is not None and obj.role in _EDIT_ROLES
        # A web document is driven by browse mode (its virtual buffer), NEVER by
        # edit-caret tracking -- otherwise arrows read the page linearly instead
        # of navigating it. Detect it by the web framework id FIRST (reliable and
        # timing-independent), falling back to the browse handler being active,
        # so a momentary is_active=False can't leave web arrows in caret mode.
        if is_edit and obj.role == "document":
            fw = (getattr(obj, "framework_id", "") or "").lower()
            is_web = fw in _WEB_DOC_FRAMEWORKS
            if not is_web and self.browse is not None:
                try:
                    is_web = bool(self.browse.is_active)
                except Exception:
                    is_web = False
            if is_web:
                is_edit = False
        if self.keyboard is not None:
            try:
                self.keyboard.is_in_edit_field = is_edit
            except Exception:
                pass
        if self.editable is not None:
            try:
                self.editable.set_element(obj if is_edit else None)
            except Exception:
                pass

    def on_edit_caret_move(self, key, ctrl):
        """Called by the keyboard hook after a non-swallowed caret movement in an
        edit field. Reads the new position once the app has moved the caret.

        A short delay lets the focused application apply the caret move before we
        query ``TextPattern.GetSelection`` (the keypress is processed only after
        the hook returns). Mirrors the C# non-blocking arrow navigation.
        """
        if self.editable is None or self._muted_for_foreground():
            return

        def _do():
            # The read itself waits for the caret to actually move before reading
            # (see EditableTextHandler._wait_caret_moved): the app applies the
            # keypress only after the hook returns, so reading on a fixed delay
            # used to announce the line/char being LEFT, not the one arrived at.
            try:
                if ctrl and key in ("left", "right"):
                    self.editable.read_caret_word()
                elif key in ("up", "down", "home", "end"):
                    self.editable.read_caret_line()
                else:  # left / right by character
                    self.editable.read_caret_char()
            except Exception as e:
                print(f"[TitanAccess] caret move read error: {e}")

        # CRITICAL: never run the read on the keyboard-hook thread. That thread
        # services the global WH_KEYBOARD_LL hook through its message loop, so a
        # blocking UIA/TextPattern call there stalls ALL keyboard input system
        # wide (this previously froze the whole app). Hand it to the dedicated
        # background reader thread instead (latest-keystroke wins).
        self.submit_read(_do)

    def on_stop_speech_key(self):
        """Ctrl pressed: silence current speech (standard screen-reader key).

        Called on the keyboard-hook thread, so it must return immediately --
        ``speech.stop()`` can block, which would stall the global hook. Offload
        it to the background worker."""
        self.request_stop_speech()

    def _handle_controller_transition(self, obj):
        """Play controller_initialize / controller_uninitialize when focus moves
        into or out of an application that drives Titan Access through the NVDA
        controller (i.e. a process that has called us via the controller)."""
        nc = self.nvda_ctl
        pids = getattr(nc, "client_pids", None) if nc is not None else None
        if not pids:
            if self._in_controller_app:
                self._in_controller_app = False
            return
        try:
            pid = (obj.process_id if obj is not None else 0) or self._foreground_pid()
            # TCE itself drives the controller (accessible_output3), but inside
            # TCE we already play enter_TCE/leave_TCE -- so never play the
            # controller earcons there, or the two cues collide.
            inside = (pid in pids) and not self._pid_is_tce(pid)
            if inside and not self._in_controller_app:
                self.play(SND_CONTROLLER_INIT)
                self._in_controller_app = True
            elif (not inside) and self._in_controller_app:
                self.play(SND_CONTROLLER_UNINIT)
                self._in_controller_app = False
        except Exception as e:
            print(f"[TitanAccess] controller transition error: {e}")

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
        # The host app (TCE) may have just spoken an exact phrase for this
        # element via announce_override (e.g. the virtual tab bar). Honour it:
        # play the cursor cue but skip our own speech so we don't double up.
        if self._consume_override():
            if play_cursor:
                self._play_element_cue(obj, for_navigation)
            return
        if play_cursor:
            self._play_element_cue(obj, for_navigation)
        # Newly-entered container context (dialog / group / list / toolbar),
        # NVDA-style focus-context presentation. This single ancestor walk ALSO
        # records whether the focused row is a status-bar slot (on the presenter)
        # so we never walk the UIA tree a second time -- a second in-process walk
        # per list row was what stalled reads inside the TCE window.
        ctx = []
        if self.context is not None:
            try:
                ctx = self.context.context_segments(
                    obj, for_navigation=for_navigation)
            except Exception as e:
                print(f"[TitanAccess] context segments error: {e}")
        # Relabel the control type for this announcement when warranted: a host
        # may pin a label via set_role_label (highest priority); otherwise the
        # context walk may have found this list row to be a status-bar slot.
        role_label_override = self._consume_role_label()
        if not role_label_override and self.context is not None:
            role_label_override = getattr(self.context, "last_status_item_label", None)
        try:
            from titan_access import accessible
            segments = accessible.describe(obj, self.settings,
                                           for_navigation=for_navigation,
                                           role_label_override=role_label_override)
        except Exception as e:
            print(f"[TitanAccess] describe error: {e}")
            segments = [(obj.name or loc.role_label(obj.role), NAME_PITCH)]
        # Prepend the container context as leading segments so it is spoken as
        # one utterance with the control's description.
        if ctx:
            segments = ctx + segments
        # Append a host-supplied state word (e.g. a wx.CheckListBox item's
        # checked/unchecked state, which UIA does not expose) at the state pitch.
        suffix = self._consume_state_suffix()
        if suffix:
            segments = segments + [(suffix, STATE_PITCH)]
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
        # Dial ("TPad"): NumPad Minus toggles it; while active, NumPad 4/6/8/2
        # drive the dial instead of object navigation.
        if self.dial is not None:
            if key_name == "numpadsubtract":
                return self.dial.toggle()
            if self.dial.enabled and key_name in ("numpad4", "numpad6",
                                                  "numpad8", "numpad2"):
                return self.dial.handle_key(key_name)
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
        g.register("sayAll", "a", self.action_say_all)
        g.register("readerMenu", "c", self.action_screen_reader_menu)

        # (Ctrl+Alt+C/W/L/P review shortcuts removed: on a Polish keyboard
        # Ctrl+Alt == AltGr, so they collided with typing diacritics. Caret
        # tracking on the arrow keys already reads char/word/line live.)

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

    def action_say_all(self, *a):
        """Insert+A: in a web document read continuously (say all); elsewhere
        re-read the focused element."""
        if (self.browse is not None and self.browse.is_active
                and not self.browse.pass_through):
            try:
                if self.browse.say_all():
                    return True
            except Exception as e:
                print(f"[TitanAccess] say all error: {e}")
        self.announce_object(self.current_object, play_cursor=False)
        return True

    def action_screen_reader_menu(self, *a):
        """Insert+C: announce and open the NVDA-style screen-reader menu.

        The menu offers reader-level actions (screen reader settings, and -- when
        the launcher is minimised to the tray -- returning to the Titan
        environment). Building / showing the wx popup is marshalled onto the GUI
        thread inside the helper.
        """
        try:
            from titan_access import reader_menu
            reader_menu.show(self)
        except Exception as e:
            print(f"[TitanAccess] screen reader menu error: {e}")
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
