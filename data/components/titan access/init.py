# -*- coding: utf-8 -*-
"""Titan Access — screen reader component entry point.

Lifecycle for the TCE component loader plus a standalone ``python init.py`` mode.

- Registers a global hotkey (General/ToggleHotkey, ``Ctrl+Shift+T`` by default) that toggles the screen reader
  on and off. The hotkey listener runs whether or not the reader is active, so
  it can also be used to turn the reader on.
- Registers the "Titan Access Screen Reader" settings category (a 1:1 port of
  the C# SettingsDialog) backed by the shared INI store.
- The actual screen reader runs on its own worker thread (own message pump,
  keyboard hook and UIA COM), so it is independent of Titan internals.
"""

import os
import sys
import threading

# --- make the component importable (dev mode does not add lib/ for us) ------ #
COMPONENT_DIR = os.path.dirname(os.path.abspath(__file__))
if COMPONENT_DIR not in sys.path:
    sys.path.insert(0, COMPONENT_DIR)
_LIB_DIR = os.path.join(COMPONENT_DIR, "lib")
if os.path.isdir(_LIB_DIR) and _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

# Add the TCE root so `src.*` imports work when running standalone from here.
_TCE_ROOT = os.path.abspath(os.path.join(COMPONENT_DIR, "..", "..", ".."))
if _TCE_ROOT not in sys.path:
    sys.path.append(_TCE_ROOT)


# =========================================================================== #
# Engine toggle
# =========================================================================== #
_toggle_lock = threading.Lock()


def is_active():
    try:
        from titan_access.engine import is_running
        return is_running()
    except Exception:
        return False


def start_reader():
    from titan_access.engine import get_engine
    try:
        _hook_titan_exits()
    except Exception as e:
        print(f"[TitanAccess] could not hook Titan's exit: {e}")
    get_engine().start()


def stop_reader():
    try:
        from titan_access.engine import TitanAccessEngine
        if TitanAccessEngine.instance is not None:
            TitanAccessEngine.instance.stop()
    except Exception as e:
        print(f"[TitanAccess] stop error: {e}")


def toggle_reader():
    """Turn the screen reader on if off, or off if on (General/ToggleHotkey, Ctrl+Shift+T by default).

    Persists the resulting state to General/Enabled, same as the settings
    checkbox, so a restart of Titan respects whatever the hotkey last left it
    at instead of only remembering the settings panel's choice.
    """
    with _toggle_lock:
        try:
            if is_active():
                print("[TitanAccess] toggling OFF")
                stop_reader()
                new_state = False
            else:
                print("[TitanAccess] toggling ON")
                start_reader()
                new_state = True
            try:
                from titan_access.settings_store import get_settings
                st = get_settings()
                st.enabled = new_state
                st.save()
            except Exception as e:
                print(f"[TitanAccess] toggle persist error: {e}")
        except Exception as e:
            print(f"[TitanAccess] toggle error: {e}")
            import traceback
            traceback.print_exc()


# =========================================================================== #
# Global hotkey listener (General/ToggleHotkey) — own thread + message pump
# =========================================================================== #
class _HotkeyListener(threading.Thread):
    """Registers the reader's shortcut (General/ToggleHotkey, Ctrl+Shift+T
    by default) via RegisterHotKey and pumps its messages. Told when the
    shortcut changes (`hotkeys.on_change`) and registers the new one on
    its own thread - a hot key belongs to the thread that registered it."""

    HOTKEY_ID = 0xA11
    MOD_NOREPEAT = 0x4000
    WM_HOTKEY = 0x0312
    WM_APP_REREGISTER = 0x8000 + 0x11

    def __init__(self, callback):
        super().__init__(daemon=True, name="TitanAccessHotkey")
        self._callback = callback
        self._thread_id = 0
        self._stop = threading.Event()
        self._registered = False

    def _register(self, user32):
        from titan_access import hotkeys
        if self._registered:
            user32.UnregisterHotKey(None, self.HOTKEY_ID)
            self._registered = False
        written = hotkeys.current()
        found = hotkeys.parse(written) or hotkeys.parse(hotkeys.DEFAULT)
        mods, vk = found
        if user32.RegisterHotKey(None, self.HOTKEY_ID,
                                 mods | self.MOD_NOREPEAT, vk):
            self._registered = True
            print(f"[TitanAccess] hotkey {written} registered")
        else:
            print(f"[TitanAccess] failed to register the {written} hotkey "
                  "(another program has it)")

    def reregister(self):
        import ctypes
        if self._thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(
                    self._thread_id, self.WM_APP_REREGISTER, 0, 0)
            except Exception:
                pass

    def run(self):
        import ctypes
        import ctypes.wintypes as wt
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        self._register(user32)
        msg = wt.MSG()
        try:
            while not self._stop.is_set():
                r = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if r == 0 or r == -1:
                    break
                if msg.message == self.WM_APP_REREGISTER:
                    try:
                        self._register(user32)
                    except Exception as e:
                        print(f"[TitanAccess] hotkey re-register error: {e}")
                    continue
                if msg.message == self.WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                    try:
                        from titan_access import hotkeys
                        if not hotkeys.field_focused:
                            self._callback()
                    except Exception as e:
                        print(f"[TitanAccess] hotkey callback error: {e}")
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            try:
                if self._registered:
                    user32.UnregisterHotKey(None, self.HOTKEY_ID)
            except Exception:
                pass

    def stop(self):
        import ctypes
        self._stop.set()
        if self._thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass


_hotkey_listener = None


def _start_hotkey():
    global _hotkey_listener
    if sys.platform != "win32":
        print("[TitanAccess] hotkey only supported on Windows")
        return
    if _hotkey_listener is None:
        _hotkey_listener = _HotkeyListener(toggle_reader)
        _hotkey_listener.start()
        try:
            from titan_access import hotkeys
            hotkeys.on_change(_reregister_hotkey)
        except Exception as e:
            print(f"[TitanAccess] hotkey change hook: {e}")


def _reregister_hotkey():
    if _hotkey_listener is not None:
        _hotkey_listener.reregister()


def _stop_hotkey():
    global _hotkey_listener
    if _hotkey_listener is not None:
        _hotkey_listener.stop()
        _hotkey_listener = None


# =========================================================================== #
# TCE component lifecycle
# =========================================================================== #
def initialize(app=None):
    """Called by the TCE ComponentManager on startup."""
    try:
        print("[TitanAccess] initializing component...")
        _start_hotkey()
        try:
            _hook_titan_exits()
        except Exception as e:
            print(f"[TitanAccess] could not hook Titan's exit: {e}")
        # Auto-start the reader if it was left enabled (the settings checkbox /
        # the hotkey persist this under General/Enabled).
        try:
            from titan_access.settings_store import get_settings
            if get_settings().enabled:
                print("[TitanAccess] auto-starting (enabled in settings)")
                start_reader()
        except Exception as e:
            print(f"[TitanAccess] auto-start check failed: {e}")
        print("[TitanAccess] ready (press the reader shortcut, Ctrl+Shift+T by default, to toggle the reader)")
    except Exception as e:
        print(f"[TitanAccess] initialize error: {e}")
        import traceback
        traceback.print_exc()


def titan_closing():
    """Titan itself is closing (not just the reader): the reader says so -
    "Trwa wyłączanie środowiska TCE", its pause, "Titan Access wyłącza się"
    - waits until that has been heard, and stops. Safe to call twice."""
    try:
        from titan_access.engine import TitanAccessEngine
        engine = TitanAccessEngine.instance
        if engine is not None and getattr(engine, "running", False):
            engine.stop(titan_closing=True)
    except Exception as e:
        print(f"[TitanAccess] titan closing: {e}")


#: Where Titan ends its own process (`os._exit`), so a component is never
#: told: the main window, and both Klango mode classes. Each is wrapped
#: once, by the component, on the live class - nothing in Titan changes.
_TITAN_EXITS = (("src.ui.gui", "TitanApp"),
                ("src.system.klangomode", "KlangoMode"),
                ("src.system.klangomode", "KlangoFrame"))


#: The thread the goodbye is said on (tests join it).
_goodbye_thread = None


def _say_goodbye_then(original, frame, args, kwargs):
    """Say the goodbye and stop the reader on a thread of their own, then
    hand Titan its own exit on its GUI thread.

    **Never on the GUI thread.** Stopping the reader waits for its worker,
    and the worker's teardown reads Titan's own windows - which only the
    GUI thread can answer. Done on the GUI thread the two waited for each
    other until the 3 s join gave up and the teardown was forced: measured,
    Titan took 11 s to close."""
    global _goodbye_thread

    def goodbye():
        try:
            titan_closing()
        finally:
            try:
                import wx
                if wx.GetApp() is None:
                    raise RuntimeError("no wx application")
                wx.CallAfter(original, frame, *args, **kwargs)
            except Exception:
                original(frame, *args, **kwargs)
    _goodbye_thread = threading.Thread(target=goodbye, daemon=True,
                                       name="TitanAccessGoodbye")
    _goodbye_thread.start()


def _hook_titan_exits():
    """Put `titan_closing` in front of Titan's own `shutdown_app`."""
    import sys
    for module_name, class_name in _TITAN_EXITS:
        module = sys.modules.get(module_name)
        cls = getattr(module, class_name, None) if module else None
        original = getattr(cls, "shutdown_app", None) if cls else None
        if original is None or getattr(original, "_titan_access", False):
            continue

        def shutdown_app(self, *args, _original=original, **kwargs):
            # Asked twice (a second Alt+F4 while the goodbye is said): the
            # second goes straight to Titan's own exit.
            if getattr(self, "_titan_access_closing", False):
                return _original(self, *args, **kwargs)
            try:
                self._titan_access_closing = True
            except Exception:
                pass
            try:
                hide = getattr(self, "Hide", None)
                if callable(hide):
                    hide()
            except Exception:
                pass
            _say_goodbye_then(_original, self, args, kwargs)
        shutdown_app._titan_access = True
        shutdown_app.__doc__ = original.__doc__
        cls.shutdown_app = shutdown_app


def shutdown():
    """Called by the TCE ComponentManager on shutdown - which is Titan
    closing (launcher mode), never the reader alone."""
    try:
        print("[TitanAccess] shutting down component...")
        titan_closing()
        stop_reader()
        _stop_hotkey()
    except Exception as e:
        print(f"[TitanAccess] shutdown error: {e}")


def add_settings_category(component_manager):
    """Register the 'Titan Access Screen Reader' settings category."""
    try:
        from titan_access.settings_panel import register
        register(component_manager)
    except Exception as e:
        print(f"[TitanAccess] settings category registration failed: {e}")
        import traceback
        traceback.print_exc()


# =========================================================================== #
# Standalone mode
# =========================================================================== #
def _standalone():
    import time
    print("=" * 60)
    print("Titan Access Screen Reader — standalone")
    print("The reader shortcut (Ctrl+Shift+T by default) toggles. Ctrl+C to quit.")
    print("=" * 60)
    _start_hotkey()
    start_reader()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_reader()
        _stop_hotkey()


# ===========================================================================
# Titan actions - what Titan, its AI and other add-ons can ask this component
# ===========================================================================
# Declared in Python rather than in an __actions.json, because the handlers are
# the component's own functions and Titan finds them on the module it already
# loaded. Either form works; a manifest file is never required.
#
# The handlers live in titan_access_actions so this file stays what it says it
# is - the component's lifecycle. The reader-state actions there need this
# module's start/stop/toggle, so it is handed over rather than imported by name
# (the component loader may load this file under any module name).

try:
    import titan_access_actions as _actions
    _actions.bind(sys.modules[__name__])
    TITAN_ACTIONS = _actions.TITAN_ACTIONS
    TITAN_DESCRIPTION = _actions.TITAN_DESCRIPTION
    # What Titan's AI is told about the reader, read out of it per prompt.
    TITAN_AI_BRIEFING = _actions.TITAN_AI_BRIEFING
except Exception as _e:                 # actions unavailable, component is not
    print(f"[TitanAccess] actions unavailable: {_e}")
    TITAN_ACTIONS = []
    TITAN_DESCRIPTION = ''
    TITAN_AI_BRIEFING = None


if __name__ == "__main__":
    _standalone()
