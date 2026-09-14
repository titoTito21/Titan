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
import queue
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
    STATE_CHECKED, STATE_PARTIAL, STATE_SELECTED,
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
        # Ordered (FIFO) background jobs -- e.g. object-navigation steps, whose
        # result depends on the position left by the PREVIOUS step, so (unlike
        # _bg_read's "latest wins" slot) rapid repeats must run every queued
        # step in order rather than collapsing to the latest.
        self._action_queue: "queue.Queue" = queue.Queue()

        # Host-app announcement hooks (TCE pushes these for widgets whose meaning
        # UIA cannot convey -- the virtual tab bar, wx.CheckListBox check state).
        self._override_until = 0.0       # suppress our next auto announce until
        self._state_suffix = None        # (text, expiry) appended to next announce
        self._role_label_override = None  # (text, expiry) replaces next role label
        # HWND of the throwaway frame that hosts our own popup menu (Insert+C).
        # Its focus must NOT be announced ("panel"/"window") -- but the popup's
        # menu / menu items (different role) still are. 0 = no menu host active.
        self._menu_host_hwnd = 0
        # True while a background AI reading for a control's missing label is
        # in flight, so a burst of nameless controls asks for one reading, not
        # one per element.
        self._ocr_label_pending = False
        # Host-declared kind for the NEXT dialog ("question"/"information"/...),
        # used when the reader cannot detect the icon (e.g. a generic wx dialog).
        # (kind, expiry); consumed by the context presenter. See host_bridge.
        self._dialog_kind_override = None
        # The focused toggle's (key, state), for hearing it change.
        self._toggle_known = None
        self._toggle_said = None

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
        self.progress = None
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
        # **And say which one is speaking.** The modules shared with the
        # NVDA add-on reach speech through `portable/compat.py`, which is
        # written against NVDA's own `speech` module and has no engine to
        # ask - so without this every ported feature was silent here and
        # perfect in NVDA, with nothing anywhere saying why.
        if self.speech is not None:
            try:
                from titan_access import speech_adapter
                speech_adapter.use(self.speech)
            except Exception:                        # noqa: BLE001
                pass

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
            if hasattr(p, "add_state_listener"):
                p.add_state_listener(self.on_state_change)
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
        # Progress bars: NVDA's rising beep, panned across the stereo image and
        # spoken every ten percent. Runs on its own slow thread.
        self.progress = _try(lambda: __import__(
            "titan_access.progress_monitor", fromlist=["ProgressMonitor"]
        ).ProgressMonitor(self).start(), "progress_monitor")

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
        self._start_shared_watchers()
        try:
            from . import jab
            ok, why = jab.start()
            print(f"[TitanAccess] Java Access Bridge: {'on' if ok else why}")
        except Exception as e:
            print(f"[TitanAccess] Java Access Bridge: {e}")

    def _start_shared_watchers(self):
        """The shared modules that WATCH rather than answer a key.

        Every one of these was vendored into `portable/` and started by
        nothing: the busy and attention watcher (`states`), the marker's
        way of finding a control by its point (`anchors`), and the touch
        recogniser that turns the pad's contacts into gestures where there
        is no NVDA tracker (`touchRecognizer`).
        """
        try:
            from .portable import readerApi
            from . import nvda_shape
            readerApi.hooks = nvda_shape.Hooks(self)
        except Exception as e:
            print(f"[TitanAccess] reader seam: {e}")
        try:
            from .portable import states
            states.start()
        except Exception as e:
            print(f"[TitanAccess] busy/attention watcher: {e}")
        try:
            from .portable import touchRecognizer
            touchRecognizer.listener = self._on_touch
        except Exception as e:
            print(f"[TitanAccess] touch hook: {e}")
        try:
            from .portable import virtualWindow
            virtualWindow.document_rows = self._document_rows
        except Exception as e:
            print(f"[TitanAccess] document rows hook: {e}")
        # The IAccessible2 proxy, so a call into Chrome or Firefox can be
        # marshalled - from the registry where NVDA or Firefox put one, or
        # registered for this process from a DLL already on the machine.
        try:
            from . import ia2
            how, detail = ia2.ensure_proxy()
            print(f"[TitanAccess] IA2 proxy: {how or 'none'} {detail}")
        except Exception as e:
            print(f"[TitanAccess] IA2 proxy: {e}")
        try:
            from .portable import monitors
            monitors.start()
        except Exception as e:
            print(f"[TitanAccess] monitors: {e}")
        try:
            from .portable import agentLink
            agentLink.start()
        except Exception as e:
            print(f"[TitanAccess] agent link: {e}")
        self._start_live_watch()

    def _java_focus(self, obj):
        """The focused control of a Java window, read through the bridge -
        where UI Automation answered a pane and nothing in it."""
        try:
            from . import jab
            if not jab.available() or obj is None or not obj.hwnd:
                return None
            if obj.role not in ('pane', 'window', 'unknown', 'group'):
                return None
            if not jab.is_java_window(obj.hwnd):
                return None
            found = jab.describe(jab.focus(obj.hwnd))
        except Exception as e:
            print(f"[TitanAccess] Java focus: {e}")
            return None
        if found is None:
            return None
        found.hwnd = obj.hwnd
        found.process_id = getattr(obj, 'process_id', 0)
        return found

    def _document_rows(self, window):
        """A web page as the virtual window's rows - the ZDSR shape.

        Titan Access already builds a virtual buffer of a web document
        (`virtual_buffer`, what browse mode walks); its nodes, in reading
        order, are what the page IS to a reader. So when the window in
        front is a browser's document the virtual window is made of them
        rather than of the browser's own tree, each row carrying the
        control's role for quick navigation and its rectangle for a click.
        """
        try:
            if self.browse is None or not self.browse.is_web:
                return None
        except Exception:
            return None
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            hwnd = 0
        if not hwnd:
            return None
        doc = getattr(self.browse, '_doc', None)
        if doc is None or getattr(doc, 'hwnd', 0) != hwnd or not doc.nodes:
            try:
                from titan_access import virtual_buffer as vbuf
                doc = vbuf.build_for_window(hwnd, allow_ocr=False)
            except Exception as e:
                print(f"[TitanAccess] document rows: {e}")
                return None
        if not doc or not doc.nodes:
            return None
        from . import nvda_shape
        rows = []
        for node in doc.nodes[:800]:
            text = ' '.join(str(node.text or '').split())
            if not text:
                continue
            rect = None
            try:
                left, top, right, bottom = node.rect
                if right > left and bottom > top:
                    rect = (int(left), int(top), int(right - left),
                            int(bottom - top))
            except Exception:
                rect = None
            obj = None
            try:
                if node.element is not None and self.provider is not None:
                    obj = nvda_shape.adapt(
                        self.provider.element_to_object(node.element),
                        self.provider)
            except Exception:
                obj = None
            role = nvda_shape.ROLE_NAMES.get(str(node.role or ''),
                                             str(node.role or '').upper())
            rows.append({'name': text, 'value': '', 'description': '',
                         'role': role or 'STATICTEXT',
                         'level': int(node.level or 0), 'obj': obj,
                         'rect': rect})
        return rows or None

    def _adapted(self, obj):
        """This reader's object in the shape the shared modules read."""
        try:
            from . import nvda_shape
            return nvda_shape.adapt(obj, self.provider)
        except Exception:
            return None

    def _object_at_point(self, x, y):
        try:
            if self.provider is not None:
                return self.provider.object_from_point(int(x), int(y))
        except Exception:
            pass
        return None

    # ---------------------------------------------------------------- #
    # Live regions: the status bar of the window in front, watched
    # ---------------------------------------------------------------- #
    LIVE_POLL = 1.5

    def _start_live_watch(self):
        """A status bar that says "connecting" with the focus elsewhere.

        NVDA delivers a name change as an event; this reader has none for
        controls the focus is not on, so the status bar of the window in
        front is READ on a slow tick and handed to the shared `live`
        module, which decides what is news and says it once.
        """
        if getattr(self, '_live_thread', None) is not None:
            return
        self._live_stop = threading.Event()

        def loop():
            last = {}
            while not self._live_stop.wait(self.LIVE_POLL):
                try:
                    from .portable import live
                    if not live.status_bars_wanted():
                        continue
                    for key, child in self._status_bar_children():
                        text = (child.name or '') + '|' + (child.value or '')
                        if last.get(key) == text:
                            continue
                        was = key in last
                        last[key] = text
                        if was:
                            live.changed(child)
                except Exception:
                    continue
        self._live_thread = threading.Thread(target=loop,
                                             name='TitanAccessLive', daemon=True)
        self._live_thread.start()

    def _status_bar_children(self):
        """``[(key, adapted child)]`` of the foreground window's status bar."""
        try:
            from . import nvda_shape
            import uiautomation as auto
        except Exception:
            return []
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            root = auto.ControlFromHandle(hwnd) if hwnd else None
        except Exception:
            root = None
        if root is None:
            return []
        found = []
        queue = [(root, 0)]
        seen = 0
        while queue and seen < 200:
            control, depth = queue.pop(0)
            seen += 1
            try:
                kind = control.ControlTypeName
            except Exception:
                continue
            if kind == 'StatusBarControl':
                try:
                    children = control.GetChildren()
                except Exception:
                    children = []
                for index, child in enumerate(children[:12]):
                    obj = None
                    try:
                        obj = self.provider.element_to_object(child)
                    except Exception:
                        obj = None
                    if obj is None:
                        continue
                    obj.role = 'statusbar'
                    found.append(('%d:%d' % (hwnd, index),
                                  nvda_shape.adapt(obj, self.provider)))
                break
            if depth < 5:
                try:
                    queue.extend((one, depth + 1)
                                 for one in control.GetChildren())
                except Exception:
                    pass
        return found

    # ---------------------------------------------------------------- #
    # A window has come to the front: the shared watchers are told
    # ---------------------------------------------------------------- #
    def _window_arrived(self, obj):
        """Once per top-level window: is it a virtual machine, a drawn
        window with nothing in it, a program with a reader module?"""
        try:
            root = ctypes.windll.user32.GetAncestor(obj.hwnd, 2) if obj.hwnd \
                else 0
        except Exception:
            root = 0
        if not root or root == getattr(self, '_arrived_at', 0):
            return
        self._arrived_at = root
        # **The window, not the first control in it.** `surface.looks_drawn`
        # refuses Explorer and the console by their window CLASS, and the
        # object that arrives first is a nameless pane with no class -
        # which has no children either, so Explorer was "a drawn window"
        # and the guest cursor announced it on every folder. The root's own
        # element carries the class.
        window = None
        try:
            if self.provider is not None:
                window = self.provider.object_from_handle(root)
        except Exception:
            window = None
        adapted = self._adapted(window if window is not None else obj)
        if adapted is None:
            return
        try:
            from .portable import guest
            guest.crossing(adapted)
            guest.consider(adapted)
        except Exception as e:
            print(f"[TitanAccess] guest: {e}")
        try:
            from .portable import surface
            surface.consider(adapted, self._module_for(adapted))
        except Exception as e:
            print(f"[TitanAccess] surface: {e}")

    def _semantic_layers(self, obj):
        """What a row MEANS and where the user IS (`semantics.py`).

        ``(before, after)`` - segments to say in front of the control (the
        place the user has moved to, said once) and behind it (the kind of
        a row out of the column a reader module names, then its columns
        as "header: cell"). Titan's own applications always; every other
        list on the machine behind the `windowsSemantics` switch.
        """
        before, after = [], []
        if obj is None:
            return before, after
        try:
            from titan_access import semantics
        except Exception:
            return before, after
        adapted = self._adapted(obj)
        if adapted is None:
            return before, after
        module = self._module_for(adapted)
        try:
            is_tce = bool(self._is_tce_foreground())
        except Exception:
            is_tce = False
        if module is None and not is_tce and not semantics.windows_wanted():
            return before, after
        # Never a web page: a row there is the browser's own business.
        fw = (getattr(obj, 'framework_id', '') or '').lower()
        if fw in _WEB_DOC_FRAMEWORKS:
            return before, after
        try:
            place = semantics.place_change(adapted, module,
                                           hwnd=getattr(obj, 'hwnd', 0))
            if place:
                before.append((place, NAME_PITCH))
        except Exception as e:
            print(f"[TitanAccess] semantics place: {e}")
        try:
            if obj.role in semantics.ROW_ROLES:
                after.extend(semantics.row_parts(
                    adapted, module, name=obj.name,
                    pitches=(NAME_PITCH, ROLE_PITCH, NAME_PITCH)))
        except Exception as e:
            print(f"[TitanAccess] semantics row: {e}")
        return before, after

    def _module_for(self, adapted):
        """The reader module for this program, or None."""
        try:
            from .portable import readerModules
            return readerModules.for_object(adapted)
        except Exception:
            return None

    def _shared_layers(self, obj):
        """What a reader module adds to a control: a word for what a ROW
        is, read off the column the module names, and a name for a pane
        the program never named. ``[(text, pitch)]`` to say after the
        control's own parts."""
        adapted = self._adapted(obj)
        if adapted is None:
            return []
        module = self._module_for(adapted)
        if module is None:
            return []
        extra = []
        try:
            from titan_access import accessible
            # (A row's kind and columns are `_semantic_layers`' now, for
            # every list on the machine and not only a module's.)
            if not (obj.name or '').strip():
                word = module.region_word(adapted, adapted.role.name, '')
                if word:
                    extra.append((word, accessible.NAME_PITCH))
        except Exception as e:
            print(f"[TitanAccess] reader module: {e}")
        return extra

    def _on_touch(self, action, x, y):
        """A gesture off the pad: a walked list first, the screen otherwise.

        Inside the virtual window, the palette or a message the gesture is
        the list's (`touchWalk`, the same table the add-on uses). Anywhere
        else one finger is the mouse: hovering reads the control under it,
        a double tap reads it again with its context - the pad standing in
        for a pointer nobody can see.
        """
        try:
            from .portable import touchWalk
            handled, said = touchWalk.handle(action, x, y)
        except Exception as e:
            print(f"[TitanAccess] touch walk: {e}")
            handled, said = False, ''
        if handled:
            if said:
                self._say(str(said))
            return
        if action in ('hover', 'double_tap', 'tap'):
            obj = self._object_at_point(x, y)
            if obj is None:
                return
            key = (obj.role, obj.name, obj.bounds)
            if action == 'hover' and key == getattr(self, '_touched', None):
                return
            self._touched = key
            try:
                self.announce_object(obj, for_navigation=True)
            except Exception as e:
                print(f"[TitanAccess] touch announce: {e}")

    def _teardown_subsystems(self):
        self._stop_bg_worker()
        for name in ('states', 'monitors', 'agentLink'):
            try:
                module = __import__('titan_access.portable.' + name,
                                    fromlist=[name])
                module.stop()
            except Exception:
                pass
        try:
            self._live_stop.set()
        except Exception:
            pass
        for name in ("keyboard", "provider", "nvda_ctl", "progress"):
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
            # Drain the ordered action queue (object-nav steps, ...) in FIFO
            # order -- every queued job runs, none are dropped/collapsed.
            while True:
                try:
                    action = self._action_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    action()
                except Exception as e:
                    print(f"[TitanAccess] bg action error: {e}")
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

    def submit_action(self, fn):
        """Queue an ordered (FIFO) background job -- e.g. an object-navigation
        step. Every queued job runs, in order, on the background thread; use
        this (not :meth:`submit_read`) whenever a job's result depends on the
        one before it, so rapid repeats can never skip/reorder a step."""
        self._action_queue.put(fn)
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
        parts = [tuple(s) for s in (segments or []) if s and s[0]]
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

    def speak_segments(self, segments, gap_ms=None):
        """Speak ``(text, pitch_offset)`` parts sequentially at their own pitch.

        ``gap_ms`` is the silence between the parts; left out, it is what
        the active speech scheme asks for.
        """
        if self.speech is None:
            return
        # Resolve pan once from the current object (virtual screen only).
        pan = self._pan_for_speech(self.current_object)
        # A segment may carry a rate and a volume behind its pitch (see
        # `accessible.split_segment`); the pan goes in the third slot,
        # which is where the concatenated speech reads it.
        full = []
        for seg in segments:
            if not seg or not seg[0]:
                continue
            pitch = seg[1] if len(seg) > 1 else 0
            rest = tuple(seg[3:5]) if len(seg) > 3 else ()
            full.append((seg[0], pitch, pan) + rest)
        gap = 0
        try:
            from .portable import speechSchemes
            gap = speechSchemes.active_pause()
        except Exception:
            gap = 0
        if gap_ms is not None:
            gap = max(int(gap or 0), int(gap_ms))
        try:
            if hasattr(self.speech, "speak_segments"):
                try:
                    self.speech.speak_segments(full, gap_ms=gap)
                except TypeError:
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

    def _auditory_icon(self, obj):
        """Emacspeak's icon for WHAT this is, beside the cue for WHERE.

        `portable/icons.py` is the add-on's own set and was reached by
        nothing here. Behind its own switch (Reader / auditoryIcons
        Everywhere), because it changes how every control sounds.
        """
        try:
            from .portable import icons
            icons.for_focus(obj)
        except Exception:
            pass

    def _dialog_kind_of(self, obj):
        """Say what kind of dialog has come up - a question, a warning, an
        error - read off the icon it holds or the answers it will take.

        Titan says it for its own dialogs (`set_dialog_kind`); everything
        else on the machine had no kind here. Once per dialog window.
        """
        if obj is None or obj.role not in ("dialog", "window") or not obj.hwnd:
            return
        if getattr(self, "_kind_said_for", 0) == obj.hwnd:
            return
        self._kind_said_for = obj.hwnd
        try:
            from .portable import dialog_kind
            if not dialog_kind.wanted():
                return
            kind, _how = dialog_kind.kind_of_window(obj.hwnd)
        except Exception:
            return
        if kind:
            try:
                self.set_dialog_kind(kind)
            except Exception:
                pass

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
        # **A walked list must not outlive its window.** The add-on ends a
        # review whose window has gone from `event_gainFocus`; nothing here
        # did, so a virtual window turned on in one program kept the
        # arrow keys in the next one - "the arrows sometimes do not work".
        self._walkers_follow_the_focus()
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
        # A focused progress bar becomes the one the monitor reports.
        if self.progress is not None:
            try:
                self.progress.on_focus(obj)
            except Exception as e:
                print(f"[TitanAccess] progress focus error: {e}")
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
        self._window_arrived(obj)
        java = self._java_focus(obj)
        if java is not None:
            obj = java
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
        # A nameless pane focused right AFTER a control is the host window
        # taking the focus back for a moment (the Alt+Tab switcher's XAML
        # island does it after every row): saying "pane" there is a word
        # about nothing, said over the row.
        if (obj.role == "pane" and not (obj.name or "").strip()
                and (now - self._last_focus_time) < 0.5):
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
                    is_web = bool(self.browse.is_web)
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
        """Ctrl / Tab pressed: silence current speech immediately.

        Called on the keyboard-hook thread.  ``speech.stop()`` is fast
        (stops the pygame channel and sets a flag), so calling it directly
        gives the most responsive interrupt.  We also set the background
        worker flag so the segment-pipeline thread (if running) notices
        the stop and exits its wait loop."""
        # Direct stop for immediate silence.
        if self.speech is not None:
            try:
                self.speech.stop()
            except Exception:
                pass
        # Also signal the background worker so segment pacing exits.
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
        self._remember_toggle(obj)
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
            self._auditory_icon(obj)
            try:
                from .portable import speechSchemes
                speechSchemes.sounded(speechSchemes.kind_of(obj.role))
            except Exception:
                pass
        self._dialog_kind_of(obj)
        # A control the program never named: borrow the caption printed on or
        # beside it from what the AI already read of this window. Only from a
        # CACHED reading here (this runs on the focus path and must not wait for
        # a vision call); a fresh reading is asked for afterwards, off-thread,
        # and its answer is spoken behind this announcement.
        self._label_unnamed(obj)
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
        # **"Unknown" is not a kind of control, it is the absence of an
        # answer.** A top-level window Windows will not classify is read as
        # "unknown"; something IS knowable - whether it is an application, a
        # game, a dialog or a little box that will go away - so the word is
        # replaced (`portable/windowKind`, the same the NVDA add-on uses).
        if not role_label_override and getattr(obj, 'role', '') in (
                'unknown', '', 'pane', 'window'):
            try:
                from .portable import windowKind
                adapted = self._adapted(obj)
                if adapted is not None:
                    kind, _how = windowKind.kind_of(adapted)
                    word = windowKind.word(kind)
                    if word:
                        role_label_override = word
            except Exception:
                pass
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
        # And what a reader module knows about this program: a name for
        # an unnamed pane.
        try:
            segments = segments + self._shared_layers(obj)
        except Exception:
            pass
        # The place the user has moved to, and the columns of a row.
        try:
            before, after = self._semantic_layers(obj)
            segments = before + segments + after
        except Exception:
            pass
        # A picture said as what it IS - an icon, a photograph, a chart -
        # rather than "graphic" (`portable/graphics.py`).
        if obj.role == 'image':
            try:
                from .portable import graphics
                adapted = self._adapted(obj)
                parts = graphics.parts(adapted) if adapted is not None else []
                if parts:
                    segments = [(part[0], part[1] if len(part) > 1 else 0)
                                for part in parts]
            except Exception:
                pass
        # If the active TTS path has no pitch control, flatten to one line.
        if self.speech is not None and not getattr(self.speech, "supports_pitch", True):
            self.speak(" ".join(s[0] for s in segments if s and s[0]), obj=obj)
        else:
            self.speak_segments(segments)
        # **And in braille**, the same control - the words the speech
        # scheme's braille rule keeps, in cells, on a display and in the
        # viewer. Off by default; a lookup and one liblouis call when on.
        try:
            from . import braille
            braille.show_object(obj)
        except Exception:
            pass

    # ==================================================================== #
    # AI OCR assistance: naming controls the program never named
    # ==================================================================== #
    # Roles where "no name" is a real accessibility failure worth spending an
    # AI reading on. A nameless pane or text block is usually just decoration.
    _NEEDS_NAME_ROLES = {
        "button", "split_button", "edit", "password", "checkbox", "radio",
        "combobox", "listitem", "menuitem", "tab", "link", "slider", "spinner",
    }

    def _label_unnamed(self, obj):
        """Give a nameless control a name, from the cheapest place that has one.

        In order (`label_finder`): the static text beside it through UI
        Automation - milliseconds, on the focus path; a name somebody
        stored for it in the shared label store (read in `describe`); a
        reading of the window already in hand, from the local recogniser
        or from the AI; and, when none of those has one, a fresh reading
        in the background - the local model first, the AI only when the
        user has AI OCR on - spoken behind the current announcement and
        remembered, so the control is asked about once.
        """
        if obj is None or (obj.name or "").strip():
            return
        if obj.role not in self._NEEDS_NAME_ROLES:
            return
        try:
            from titan_access import label_finder
        except Exception:
            label_finder = None
        hwnd = getattr(obj, "hwnd", 0) or 0
        bounds = getattr(obj, "bounds", None)
        if label_finder is not None:
            try:
                label = label_finder.from_uia(obj)
            except Exception:
                label = ""
            if label:
                obj.name = label
                return
            if bounds and hwnd:
                try:
                    label = label_finder.from_local_ocr(obj, hwnd,
                                                        cached_only=True)
                except Exception:
                    label = ""
                if label:
                    obj.name = label
                    return
        if not bounds:
            return
        if self._ocr_labels_enabled():
            try:
                from titan_access import ocr_assist
                label = ocr_assist.label_for(hwnd, tuple(bounds), self.settings) \
                    if ocr_assist.available(self.settings) else ""
            except Exception:
                label = ""
            if label:
                obj.name = label
                return
        self._request_ocr_label(obj, hwnd, tuple(bounds))

    def _ocr_labels_enabled(self) -> bool:
        try:
            value = self.settings.get("Reader", "AiOcrLabels")
        except Exception:
            return True
        if value in (None, ""):
            return True
        return str(value).strip().lower() not in ("0", "false", "no", "off")

    def _request_ocr_label(self, obj, hwnd, bounds):
        """Read the window in the background and speak the label if one turns up."""
        if not hwnd or getattr(self, "_ocr_label_pending", False):
            return
        self._ocr_label_pending = True
        token = self._announce_token

        def _work():
            label = ""
            source = ""
            try:
                # The local model first: private, free, and it reads the
                # whole window once for every unnamed control in it.
                from titan_access import label_finder
                label = label_finder.from_local_ocr(obj, hwnd)
                source = "ocr" if label else ""
            except Exception as e:
                if os.environ.get("TITAN_ACCESS_DEBUG"):
                    print(f"[TitanAccess] local OCR label failed: {e}")
            if not label and self._ocr_labels_enabled():
                try:
                    from titan_access import ocr_assist
                    if ocr_assist.available(self.settings):
                        label = ocr_assist.label_for(hwnd, bounds, self.settings)
                        source = "ai" if label else ""
                except Exception as e:
                    if os.environ.get("TITAN_ACCESS_DEBUG"):
                        print(f"[TitanAccess] OCR label failed: {e}")
            self._ocr_label_pending = False
            if not label:
                return
            # Remembered, in the store both readers share, so it is asked
            # about once in its life.
            try:
                from titan_access import label_finder
                label_finder.remember(self._adapted(obj), label, source="ai")
            except Exception:
                pass
            # Only if the user is still on the same element: a label for a
            # control they have already left is noise.
            if token == self._announce_token and self.current_object is obj:
                obj.name = label
                self.speak(label, obj=obj, interrupt=False)

        threading.Thread(target=_work, daemon=True).start()

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
    def on_modifier_gesture(self, vk, key_name, ctrl, alt, shift,
                            with_modifier=False) -> bool:
        """A key with the reader modifier held, or a bare NumPad key.

        ``with_modifier`` says which: the hook calls this for both, and
        the bare NumPad minus is the dial's (or a terminal's review)
        while **Insert+NumPad minus is the virtual window** - so the
        dial and the app module may claim the key only when the modifier
        is NOT held, or the gesture registered for Insert+minus was
        never reached.
        """
        # NumPad Minus: the active app module gets first claim (the terminal
        # module toggles its screen review with it, just like the dial's own
        # toggle), and only if no module wants it does it toggle the dial. This
        # lets NumPad Minus mean "review" inside a terminal and "dial" everywhere
        # else, without either shadowing the other.
        if (key_name == "numpadsubtract" and not with_modifier
                and self.app_modules is not None):
            try:
                if self.app_modules.handle_plain_key(vk, key_name, ctrl, alt, shift):
                    return True
            except Exception as e:
                print(f"[TitanAccess] app modifier claim error: {e}")
        # Dial ("TPad"): NumPad Minus toggles it; while active, NumPad 4/6/8/2
        # drive the dial instead of object navigation.
        if self.dial is not None and not with_modifier:
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

    #: What the walked lists answer, by the name this reader's own hook
    #: gives a key. The shared modules are written against NVDA's
    #: spellings and their own; `textField.bare_name` knows both, so what
    #: is passed on is whatever was pressed.
    WALKED_KEYS = ('up', 'down', 'left', 'right', 'home', 'end',
                   'pageup', 'pagedown', 'return', 'enter', 'escape',
                   'backspace', 'delete', 'f5', 'space', 'tab')

    def _walkers_follow_the_focus(self):
        """End any walked list whose window is no longer in front."""
        for name in ('virtualWindow', 'ocrReview', 'palette'):
            try:
                import importlib
                module = importlib.import_module('.portable.%s' % name,
                                                 __package__)
                module.left_the_window()
            except Exception:                        # noqa: BLE001
                continue
        try:
            from .portable import smart
            if smart.active() and smart.window() != self._foreground_hwnd():
                smart.forget()
        except Exception:                            # noqa: BLE001
            pass

    @staticmethod
    def _foreground_hwnd():
        try:
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            return int(user32.GetForegroundWindow() or 0)
        except Exception:                            # noqa: BLE001
            return 0

    def _walked_key(self, vk, key_name, ctrl, alt, shift) -> bool:
        """The ported walkers get their keys here. ``True`` when one took it.

        **The other half of sharing a module.** `virtualWindow`, `palette`
        and `textField` are byte-identical in both readers, and in NVDA
        the plugin borrows the arrows for them; here nothing did - so the
        virtual window turned ON in this reader and no key walked it,
        which is a feature that reports success and cannot be used.

        Runs on the hook thread, so everything it calls is local: moving
        a cursor in a list already in hand, never a round trip.
        """
        name = str(key_name or '').lower()
        if alt:
            return False
        # **The smart OCR cursor over a drawn window** (`portable/smart.py`):
        # Tab and the up/down arrows walk the controls that were read,
        # Enter presses, Escape gives the keys back - Left and Right are
        # never taken, because in a game they are the game's.
        try:
            from .portable import smart
            if smart.active() and smart.window() == self._foreground_hwnd():
                if name in ('tab', 'down', 'numpad2') and not shift:
                    smart.say(smart.move(1))
                    return True
                if name in ('up', 'numpad8') or (name == 'tab' and shift):
                    smart.say(smart.move(-1))
                    return True
                if name in ('return', 'enter'):
                    ok, said = smart.press()
                    if said:
                        self._say(str(said))
                    return True
                if name == 'escape':
                    smart.forget()
                    return True
        except Exception:
            pass
        # **The same keys as the NVDA add-on, key for key.** Left and
        # Right follow the layout (a character, the word or control
        # beside, the row beside), Shift the other way round, Control by
        # word; Numpad 7/9/1/3 are the four corners, Numpad 4/6 the
        # layout - one setting for the palette, a message and the
        # virtual window alike (`virtualWindow.LAYOUTS`).
        try:
            from .portable import palette
            if palette.walking():
                said = ''
                if name in ('up', 'numpad8'):
                    palette.move(-1)
                elif name in ('down', 'numpad2'):
                    palette.move(1)
                elif name == 'left':
                    if ctrl:
                        palette.move_word(-1)
                    elif shift:
                        palette.move_across_shift(-1)
                    else:
                        palette.move_across(-1)
                elif name == 'right':
                    if ctrl:
                        palette.move_word(1)
                    elif shift:
                        palette.move_across_shift(1)
                    else:
                        palette.move_across(1)
                elif name == 'home':
                    palette.move_end(False)
                elif name == 'end':
                    palette.move_end(True)
                elif name == 'numpad7':
                    palette.move_corner(-1, -1)
                elif name == 'numpad9':
                    palette.move_corner(1, -1)
                elif name == 'numpad1':
                    palette.move_corner(-1, 1)
                elif name == 'numpad3':
                    palette.move_corner(1, 1)
                elif name == 'numpad4':
                    _ok, said = palette.layout_cycle(-1)
                elif name == 'numpad6':
                    _ok, said = palette.layout_cycle(1)
                elif name in ('return', 'enter'):
                    # What a row answered is only RETURNED by the module
                    # (the add-on's plugin says it); a setting flipped in
                    # place was silent here for want of this line.
                    _ok, said = palette.activate()
                elif name == 'escape':
                    _ok, said = palette.back()
                else:
                    return False
                if said:
                    self._say(str(said))
                return True
        except Exception:                            # noqa: BLE001
            pass
        try:
            from .portable import virtualWindow
        except Exception:                            # noqa: BLE001
            return False
        try:
            if not virtualWindow.reviewing():
                return False
            if virtualWindow.typing_mode():
                if name == 'escape':
                    _ok, said = virtualWindow.leave_typing()
                    if said:
                        self._say(str(said))
                    return True
                # Everything else is the field's: the letters, the space,
                # the arrows, Backspace. `type_key` hands back anything
                # the field does not want.
                held = []
                if ctrl:
                    held.append('ctrl')
                if shift:
                    held.append('shift')
                whole = '+'.join(held + [name])
                _ok, said = virtualWindow.type_key(whole, lambda: None)
                if said:
                    self._say(str(said))
                return True
            if name in ('up', 'numpad8'):
                virtualWindow.move(-1)
            elif name in ('down', 'numpad2'):
                virtualWindow.move(1)
            elif name == 'left':
                if ctrl:
                    virtualWindow.move_word(-1)
                elif shift:
                    virtualWindow.move_across_shift(-1)
                else:
                    virtualWindow.move_across(-1)
            elif name == 'right':
                if ctrl:
                    virtualWindow.move_word(1)
                elif shift:
                    virtualWindow.move_across_shift(1)
                else:
                    virtualWindow.move_across(1)
            elif name == 'home':
                virtualWindow.move_end(False)
            elif name == 'end':
                virtualWindow.move_end(True)
            elif name == 'pageup':
                virtualWindow.move_page(-1)
            elif name == 'pagedown':
                virtualWindow.move_page(1)
            elif name == 'numpad7':
                virtualWindow.move_diagonal(-1, -1)
            elif name == 'numpad9':
                virtualWindow.move_diagonal(1, -1)
            elif name == 'numpad1':
                virtualWindow.move_diagonal(-1, 1)
            elif name == 'numpad3':
                virtualWindow.move_diagonal(1, 1)
            elif name == 'numpad4':
                _ok, said = virtualWindow.layout_cycle(-1)
                if said:
                    self._say(str(said))
            elif name == 'numpad6':
                _ok, said = virtualWindow.layout_cycle(1)
                if said:
                    self._say(str(said))
            elif name == 'numpad5':
                _ok, said = virtualWindow.click_mouse()
                if said:
                    self._say(str(said))
            elif name in ('return', 'enter'):
                _ok, said = virtualWindow.activate()
                if said:
                    self._say(str(said))
            elif name == 'f5':
                _ok, said = virtualWindow.refresh()
                if said:
                    self._say(str(said))
            elif name == 'escape':
                if virtualWindow.in_a_menu():
                    virtualWindow.close_menu()
                else:
                    _on, said = virtualWindow.stop()
                    if said:
                        self._say(str(said))
            else:
                return False
            return True
        except Exception as error:                   # noqa: BLE001
            print(f"[TitanAccess] walked-key error: {error}")
            return False

    def on_walked_numpad(self, vk, key_name, shift) -> bool:
        """A NumPad key with NumLock off, BEFORE object navigation gets it.

        Those keys reach the hook as ``numpad7`` and the like and go to
        the object navigator - which is right everywhere except inside a
        walked list, where Numpad 7/9/1/3 are the corners and 4/6 the
        layout, exactly as in the NVDA add-on. Answers False at once when
        no walker is up, so object navigation is untouched otherwise.
        """
        return self._walked_key(vk, key_name, False, False, shift)

    def on_plain_key(self, vk, key_name, ctrl, alt, shift) -> bool:
        # A guest's screen: a navigation key is the guest's, and what it
        # moved onto is read from the picture a moment later.
        try:
            from .portable import guest
            if guest.following() and str(key_name or '').lower() in (
                    'up', 'down', 'left', 'right', 'home', 'end', 'tab',
                    'return', 'enter', 'pageup', 'pagedown'):
                threading.Timer(0.15, lambda: guest.after_key()).start()
        except Exception:
            pass
        # **Space on a check box is a change worth hearing.** Nothing
        # moves the focus when a box is ticked, so no focus event says
        # so; the control is read again a moment after the key and the
        # new state is said - "checked", a pause, "check box".
        if key_name == "space" and not ctrl and not alt:
            self._expect_toggle(self.current_object)
        # **The walked lists first.** They are explicit modes the user
        # turned on, so while one is up its keys are its own - the same
        # rule the NVDA add-on follows by borrowing the gestures.
        try:
            if self._walked_key(vk, key_name, ctrl, alt, shift):
                return True
        except Exception:                            # noqa: BLE001
            pass
        # Browse mode quick-nav / arrows take precedence when active.
        try:
            if self.browse is not None and self.browse.is_active:
                if self.browse.handle_key(vk, key_name, ctrl, alt, shift):
                    return True
        except Exception:
            pass
        # Active application module's own plain-key layer (e.g. the terminal
        # screen-review cursor: minus toggles it, arrows / PageUp / PageDown
        # drive it). Runs on the hook thread, so a module MUST keep this fast.
        try:
            if self.app_modules is not None:
                if self.app_modules.handle_plain_key(vk, key_name, ctrl, alt, shift):
                    return True
        except Exception as e:
            print(f"[TitanAccess] app plain-key error: {e}")
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

        # **The virtual window, and the touchpad** - the two the NVDA
        # add-on has and this reader did not. `minus` is Insert+minus,
        # which is free here and is what the user asked for; the virtual
        # window is on `w`, beside the other reading commands.
        g.register("virtualWindow", "w", self.action_toggle_virtual_window)
        # **Insert+minus opens the virtual window** - on the NumPad minus
        # (which this reader's own hook names `numpadsubtract`, whatever
        # NumLock says) and on the top-row minus (named `-`, never
        # `minus`: the old `minus` spec matched no key at all, so the
        # trackpad it was meant to toggle was reachable from nowhere).
        # The touchpad moved to Shift with the same key. The NVDA add-on
        # has the virtual window on a bare NumPad minus; here that key is
        # the dial's, so it is the modifier that tells them apart.
        g.register("virtualWindow", "numpadsubtract",
                   self.action_toggle_virtual_window)
        g.register("virtualWindow", "-", self.action_toggle_virtual_window)
        # **Insert+Shift+Space is the palette.** It was on `space`, the
        # same spec browse mode is on - and the first binding registered
        # wins, so the palette never opened from the keyboard.
        g.register("commandPalette", "shift+space", self.action_command_palette)
        g.register("titanWindow", "i", self.action_titan_window)
        # **Insert+Ctrl+G: the reader's own settings, walked** - every
        # section and every switch as a list the arrows walk, the way the
        # add-on walks Titan's settings, so the reader can be configured
        # without the settings window being anywhere on the screen.
        g.register("readerSettings", "control+g",
                   self.action_reader_settings_window)
        # The Titan MENU, on the key the add-on puts it on - the same
        # menu, walked, rather than a second list of the same things.
        g.register("titanMenu", "shift+t", self.action_titan_menu)
        g.register("trackpad", "shift+numpadsubtract",
                   self.action_toggle_trackpad)
        g.register("trackpad", "shift+-", self.action_toggle_trackpad)
        # The reader's manager, walked - markers, monitors, the auditory
        # icons, the sound scheme, the voices - on the key the add-on has
        # it on (NVDA+shift+j there, Insert+shift+j here). The module was
        # vendored and reached by nothing, so a user of this reader had
        # no way to see what they had made or to choose a sound.
        g.register("readerManager", "shift+j", self.action_reader_manager)
        # The next speech scheme (NVDA+alt+s in the add-on). The schemes
        # themselves are a page of the walked manager.
        g.register("speechScheme", "shift+s", self.action_speech_scheme)
        # Place markers, shared with the add-on's own store: mark the
        # control you are on (by its place on the screen, which is what
        # this reader can find again), and go back to one.
        g.register("markHere", "shift+k", self.action_mark_here)
        g.register("goToMarker", "k", self.action_go_to_marker)
        # Procedures - a recorded sequence of "go to this control, press
        # it, type this" - shared with the add-on's own store: record
        # (start / stop) and run.
        g.register("recordProcedure", "shift+r", self.action_record_procedure)
        g.register("runProcedure", "r", self.action_run_procedure)
        # Watch a control's value, and say what changed.
        g.register("watchControl", "shift+w", self.action_watch_control)

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

    # ------------------------------------------------------------------ #
    # The reader's own settings, walked (Insert+Ctrl+G)
    # ------------------------------------------------------------------ #
    def action_reader_settings_window(self, *_args):
        """Every section and every switch of this reader as a walked list.

        The same shape the NVDA add-on gives Titan's settings (category
        first, then the controls, Enter does the one obvious thing to
        each kind), on this reader's OWN store - so it needs no Titan
        window and no bridge, and works with nothing on the screen.
        """
        try:
            from . import settings_walk
        except Exception as error:                   # noqa: BLE001
            self._say("Settings: %s" % error)
            return False
        try:
            ok, said = settings_walk.open_it(self)
        except Exception as error:                   # noqa: BLE001
            self._say("Settings: %s" % error)
            return False
        if not ok and said:
            self._say(str(said))
        return True

    # ------------------------------------------------------------------ #
    # A check box ticked: "checked", a pause, "check box"
    # ------------------------------------------------------------------ #
    #: Roles whose STATE can change under the focus without the focus
    #: moving - and therefore without any focus event saying so.
    _TOGGLE_ROLES = ("checkbox", "radio", "menuitem", "button",
                     "listitem", "treeitem")
    #: The silence between the state and the control type, at least.
    TOGGLE_PAUSE_MS = 250
    #: How long after Space the control is read again.
    TOGGLE_REREAD_S = 0.15

    @staticmethod
    def _toggle_key(obj):
        if obj is None:
            return None
        return (getattr(obj, "role", ""), getattr(obj, "name", "") or "",
                getattr(obj, "automation_id", "") or "",
                int(getattr(obj, "hwnd", 0) or 0))

    @staticmethod
    def _toggle_state(obj):
        """The one word this control's toggle state is, or '' when the
        control has no such state at all (an ordinary list row)."""
        if obj is None:
            return ""
        role = getattr(obj, "role", "")
        has = getattr(obj, "has", None)
        if not callable(has):
            return ""
        if has(STATE_PARTIAL):
            return "partial"
        if has(STATE_CHECKED):
            return "checked"
        if role == "checkbox":
            return "unchecked"
        if role == "button":
            return "pressed" if has("pressed") else ""
        if role == "radio":
            return "selected" if (has(STATE_SELECTED) or has(STATE_CHECKED)) \
                else "unselected"
        if role == "menuitem":
            # A plain menu item has no check at all; only one that was
            # checked and is now not is worth a word.
            return "unchecked" if has("checkable") else ""
        return ""

    def _remember_toggle(self, obj):
        """What the focused control's state is, so a change can be told
        from the state it arrived with."""
        try:
            if getattr(obj, "role", "") in self._TOGGLE_ROLES:
                self._toggle_known = (self._toggle_key(obj),
                                      self._toggle_state(obj))
            else:
                self._toggle_known = None
        except Exception:                            # noqa: BLE001
            self._toggle_known = None

    def _expect_toggle(self, obj):
        """Space was pressed on *obj*: read it again shortly and say the
        new state if it changed. Never on the hook thread."""
        if obj is None or getattr(obj, "role", "") not in self._TOGGLE_ROLES:
            return
        key = self._toggle_key(obj)
        # The state as last HEARD, not as the focus snapshot holds it: the
        # snapshot is from before the first Space, so the second Space
        # would compare the new state with a stale one and say nothing.
        known = getattr(self, "_toggle_known", None)
        before = known[1] if known and known[0] == key else \
            self._toggle_state(obj)
        if not before and obj.role in ("listitem", "treeitem", "menuitem"):
            # A row that is not checkable: Space selects it, and the
            # focus path already says so.
            return

        def _later():
            try:
                fresh = self.provider.get_focused_object() \
                    if self.provider is not None else None
            except Exception:                        # noqa: BLE001
                fresh = None
            if fresh is None or self._toggle_key(fresh) != key:
                return
            after = self._toggle_state(fresh)
            if after and after != before:
                self._announce_toggle(fresh, after)
        threading.Timer(self.TOGGLE_REREAD_S, _later).start()

    def on_state_change(self, obj):
        """A state changed somewhere (MSAA ``EVENT_OBJECT_STATECHANGE``,
        which UI Automation also raises for its own controls): if it is
        the focused toggle and its state really moved, say so. Anything
        else - a button being enabled in another window - is not news."""
        known = getattr(self, "_toggle_known", None)
        if obj is None or not known:
            return
        key, state = known
        if self._toggle_key(obj) != key:
            return
        now = self._toggle_state(obj)
        if now and now != state:
            self._announce_toggle(obj, now)

    def toggle_segments(self, obj, state):
        """``[(state word, pitch), (control type, pitch)]`` - the shape the
        user asked for: "checked", a pause, "check box"."""
        word = L("toggle." + state)
        role = getattr(obj, "role", "")
        try:
            from titan_access import accessible
            custom_role = str(accessible._custom_for(obj).get("role_word") or "")
        except Exception:                            # noqa: BLE001
            custom_role = ""
        kind = custom_role or loc.role_label(role)
        parts = [(word, STATE_PITCH)]
        if kind:
            parts.append((kind, ROLE_PITCH))
        return parts

    def _announce_toggle(self, obj, state):
        key = self._toggle_key(obj)
        now = time.time()
        last = getattr(self, "_toggle_said", None)
        if last and last[0] == key and last[1] == state and now - last[2] < 0.6:
            return
        self._toggle_said = (key, state, now)
        self._toggle_known = (key, state)
        try:
            self.speak_segments(self.toggle_segments(obj, state),
                                gap_ms=self.TOGGLE_PAUSE_MS)
        except Exception as e:
            print(f"[TitanAccess] toggle announce error: {e}")

    # ------------------------------------------------------------------ #
    # The virtual window and the touchpad
    # ------------------------------------------------------------------ #
    def action_toggle_virtual_window(self, *_args):
        """Any window as a flat list the arrows walk.

        The same subsystem the NVDA add-on has, shared as one file - and
        the same fallback: a window that exposes nothing at all, which a
        virtual machine's guest screen is, is READ by Windows' own
        recogniser and its lines become the rows. Enter then clicks where
        the words really are, which is the only way to press anything
        inside somebody else's computer.
        """
        try:
            from .portable import virtualWindow
        except Exception as error:                   # noqa: BLE001
            self._say("Virtual window: %s" % error)
            return False
        try:
            ok, said = virtualWindow.toggle()
        except Exception as error:                   # noqa: BLE001
            self._say("Virtual window: %s" % error)
            return False
        if said:
            self._say(str(said))
        return bool(ok)

    def action_command_palette(self, *_args):
        """The command palette, walked - the same one the add-on has.

        A list of layers, then a list of the commands in one, then Enter.
        Shared as one file, so the two readers cannot drift apart about
        what is on it.
        """
        try:
            from .portable import layers, palette
        except Exception as error:                   # noqa: BLE001
            self._say("Palette: %s" % error)
            return False
        names = layers.names()
        if not names:
            return False
        rows = []
        for name in names:
            rows.append({
                'label': '%s (%d)' % (layers.label(name),
                                      len(layers.keys_of(name))),
                'role': '',
                'run': (lambda chosen=name: self._palette_layer(chosen)),
            })
        ok, _said = palette.show(rows, "Titan")
        return bool(ok)

    def _palette_layer(self, layer):
        """One layer's commands. Enter runs the one the cursor is on."""
        from .portable import layers, palette
        rows = []
        for key in sorted(layers.keys_of(layer)):
            command, said = layers.keys_of(layer)[key]
            try:
                text = said() if callable(said) else str(command)
            except Exception:                        # noqa: BLE001
                text = str(command)
            rows.append({'label': '%s (%s)' % (text, key), 'role': '',
                         'run': (lambda one=command: self._palette_run(one))})
        return palette.show(rows, layers.label(layer),
                            back=self.action_command_palette)

    #: Palette commands this reader answers ITSELF rather than through the
    #: shared `commands` module - because what they mean here is genuinely
    #: different, not because the shared one is missing.
    MINE = {
        'status': 'action_read_window_title',
        'read_locally': 'action_toggle_virtual_window',
    }

    def _palette_run(self, command):
        """Run a palette command HERE.

        **The commands are shared now**, so most of them are the very same
        function the add-on runs - one source, two readers. A handful mean
        something different in this reader and are answered above; a
        handful more are genuinely NVDA's own (its speech filter, its audio
        session, its review cursor) and say so out loud rather than
        pretending, which is what `commands` itself does when a part it
        reaches for is not here.
        """
        from .portable import palette
        palette.stop()
        name = str(command or '')
        own = self.MINE.get(name)
        if own:
            getattr(self, own)()
            return True, ''
        try:
            from .portable import commands
        except Exception as error:                   # noqa: BLE001
            self._say("%s: %s" % (name, error))
            return False, ''
        work = getattr(commands, name, None)
        if not callable(work):
            self._say("%s: not in this reader" % name)
            return False, ''
        try:
            work()
        except ImportError as error:                 # noqa: BLE001
            self._say("%s: this reader has not got that (%s)"
                      % (name, error))
            return False, ''
        except Exception as error:                   # noqa: BLE001
            self._say("%s: %s" % (name, error))
            return False, ''
        return True, ''

    def action_titan_menu(self, *_args):
        """The Titan menu, walked - the SAME menu the add-on puts up.

        Not a second list of Titan's actions: `menu.build()` is one
        definition of what is on the Titan menu and in what order, and
        `menuWalk` walks that, so the two readers cannot quietly stop
        agreeing about it. What differs is only the frame it belongs to,
        which `compat.gui` answers for each.
        """
        try:
            from .portable import menuWalk
        except Exception as error:                   # noqa: BLE001
            self._say("Titan: %s" % error)
            return False
        try:
            ok, said = menuWalk.open_it(None)
        except Exception as error:                   # noqa: BLE001
            self._say("Titan: %s" % error)
            return False
        if not ok and said:
            self._say(str(said))
        return bool(ok)

    def action_titan_window(self, *_args):
        """Titan itself, walked: the pages, and what is on a page.

        The same module the add-on uses, and it reaches Titan the same
        way - except that here `LINK` is Titan's own doorway rather than
        a pipe, so there is nothing to wait for.
        """
        try:
            from .portable import titanWalk
        except Exception as error:                   # noqa: BLE001
            self._say("Titan: %s" % error)
            return False
        try:
            ok, _said = titanWalk.open_it()
        except Exception as error:                   # noqa: BLE001
            self._say("Titan: %s" % error)
            return False
        return bool(ok)

    def action_mark_here(self, *_args):
        """Mark the control the reader is on - the shared module's own
        `mark`, so a marker made here is found by the add-on and back."""
        adapted = self._adapted(self.current_object)
        if adapted is None:
            self._say(L("engine.noCurrentElement"))
            return False
        try:
            from .portable import markers
            ok, said = markers.mark(adapted)
        except Exception as e:
            self._say("Marker: %s" % e)
            return False
        if said:
            self._say(str(said))
        return bool(ok)

    def action_go_to_marker(self, *_args):
        """Choose one of the markers and read what is there now."""
        try:
            from .portable import markers, anchors, palette
            found = markers.all_markers()
        except Exception as e:
            self._say("Marker: %s" % e)
            return False
        if not found:
            self._say(markers._('There is no such marker'))
            return False

        def go(marker):
            def run():
                palette.stop()
                ok, said = markers.go(marker)
                if said:
                    self._say(str(said))
                return bool(ok), ''
            return run
        rows = [{'label': str(one.get('name') or ''), 'role': '',
                 'run': go(one)} for one in found]
        ok, said = palette.show(rows, markers._('Markers'))
        if said:
            self._say(str(said))
        return bool(ok)

    def action_record_procedure(self, *_args):
        """Start recording a procedure, or stop and keep it."""
        try:
            from .portable import procedures
            if procedures.recording():
                ok, said = procedures.stop_recording()
            else:
                ok, said = procedures.start_recording()
        except Exception as e:
            self._say("Procedure: %s" % e)
            return False
        if said:
            self._say(str(said))
        return bool(ok)

    def action_run_procedure(self, *_args):
        """Choose one of the procedures and run it."""
        try:
            from .portable import procedures, palette
            found = procedures.all_procedures()
        except Exception as e:
            self._say("Procedure: %s" % e)
            return False
        if not found:
            self._say(procedures._('There is no such procedure')
                      if hasattr(procedures, '_') else 'No procedures')
            return False

        def run_it(procedure):
            def run():
                palette.stop()
                def work():
                    try:
                        ok, said = procedures.run(procedure, say=self._say)
                        if said:
                            self._say(str(said))
                    except Exception as e:
                        self._say("Procedure: %s" % e)
                threading.Thread(target=work, name='TitanAccessProcedure',
                                 daemon=True).start()
                return True, ''
            return run
        rows = [{'label': str(one.get('name') or ''), 'role': '',
                 'run': run_it(one)} for one in found]
        ok, said = palette.show(rows, procedures._('Procedures')
                                if hasattr(procedures, '_') else 'Procedures')
        if said:
            self._say(str(said))
        return bool(ok)

    def action_watch_control(self, *_args):
        """Watch the control the reader is on; say when it changes."""
        adapted = self._adapted(self.current_object)
        if adapted is None:
            self._say(L("engine.noCurrentElement"))
            return False
        try:
            from .portable import monitors
            ok, said = monitors.watch_this_control(adapted)
        except Exception as e:
            self._say("Monitor: %s" % e)
            return False
        if said:
            self._say(str(said))
        return bool(ok)

    def action_speech_scheme(self, *_args):
        """The next speech scheme - how each kind of control is announced -
        made the one in force, and said."""
        try:
            from .portable import speechSchemes
            _key, label = speechSchemes.cycle(1)
        except Exception as error:                   # noqa: BLE001
            self._say("Speech scheme: %s" % error)
            return False
        self._say(speechSchemes._('Scheme: {name}').format(name=label))
        return True

    def action_reader_manager(self, *_args):
        """What the user has made, walked: markers, programs, procedures,
        names, monitors, the auditory icons, the sound scheme, the voices.

        The same `managerWalk` the NVDA add-on has, so both readers show
        the same things in the same order. The form the add-on also
        offers is NVDA's own window and is not here; every level of the
        walk says so where it would have opened it.
        """
        try:
            from .portable import managerWalk
        except Exception as error:                   # noqa: BLE001
            self._say("Manager: %s" % error)
            return False
        try:
            ok, said = managerWalk.open_it()
        except Exception as error:                   # noqa: BLE001
            self._say("Manager: %s" % error)
            return False
        if not ok and said:
            self._say(str(said))
        return bool(ok)

    def action_speech_schemes(self, *_args):
        """The speech schemes, walked (a page of the reader manager)."""
        try:
            from .portable import managerWalk
            ok, said = managerWalk._open_page('schemes')
        except Exception as error:                   # noqa: BLE001
            self._say("Schemes: %s" % error)
            return False
        if not ok and said:
            self._say(str(said))
        return bool(ok)

    def action_class_manager(self, *_args):
        """The voice classes as a form (the class manager)."""
        try:
            from .portable import managerWalk
            ok, said = managerWalk._as_a_form('classes')
        except Exception as error:                   # noqa: BLE001
            self._say("Class manager: %s" % error)
            return False
        if not ok and said:
            self._say(str(said))
        return bool(ok)

    def action_sound_manager(self, *_args):
        """Markers, monitors, procedures, icons and sounds as a form."""
        try:
            from .portable import managerWalk
            ok, said = managerWalk._as_a_form('manager')
        except Exception as error:                   # noqa: BLE001
            self._say("Manager: %s" % error)
            return False
        if not ok and said:
            self._say(str(said))
        return bool(ok)

    def action_toggle_trackpad(self, *_args):
        """The laptop's touchpad as a touch screen.

        Every Windows laptop made in the last decade has a multi-touch
        surface under the user's hands and to a screen reader it is a
        mouse. It is a HID digitizer: every contact has an identifier and
        a position, and mapping the pad onto the screen absolutely is what
        makes it a touch screen rather than a pointer.
        """
        try:
            from .portable import trackpad
        except Exception as error:                   # noqa: BLE001
            self._say("Touchpad: %s" % error)
            return False
        try:
            ok, said = trackpad.toggle()
        except Exception as error:                   # noqa: BLE001
            self._say("Touchpad: %s" % error)
            return False
        if said:
            self._say(str(said))
        return bool(ok)

    def _say(self, text):
        """One sentence, through this reader's own speech."""
        try:
            from . import speech_adapter
            speech_adapter.speak(str(text or ""))
        except Exception:                            # noqa: BLE001
            pass

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
        """Reader modifier + Space.

        In a web document it switches between browse and focus mode. In an
        ORDINARY application it switches scan mode on and off: the app's own
        interface becomes a virtual document with the same arrows and the same
        quick-navigation letters as a web page (see
        :class:`titan_access.browse_mode.BrowseModeHandler`).
        """
        if self.browse is not None:
            try:
                return bool(self.browse.toggle())
            except Exception as e:
                print(f"[TitanAccess] browse toggle error: {e}")
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
