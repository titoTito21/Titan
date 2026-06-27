# -*- coding: utf-8 -*-
"""Titan Access — screen reader component entry point.

Lifecycle for the TCE component loader plus a standalone ``python init.py`` mode.

- Registers a global ``Ctrl+Shift+Alt+T`` hotkey that toggles the screen reader
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
    get_engine().start()


def stop_reader():
    try:
        from titan_access.engine import TitanAccessEngine
        if TitanAccessEngine.instance is not None:
            TitanAccessEngine.instance.stop()
    except Exception as e:
        print(f"[TitanAccess] stop error: {e}")


def toggle_reader():
    """Turn the screen reader on if off, or off if on (Ctrl+Shift+Alt+T)."""
    with _toggle_lock:
        try:
            if is_active():
                print("[TitanAccess] toggling OFF")
                stop_reader()
            else:
                print("[TitanAccess] toggling ON")
                start_reader()
        except Exception as e:
            print(f"[TitanAccess] toggle error: {e}")
            import traceback
            traceback.print_exc()


# =========================================================================== #
# Global hotkey listener (Ctrl+Shift+Alt+T) — own thread + message pump
# =========================================================================== #
class _HotkeyListener(threading.Thread):
    """Registers Ctrl+Shift+Alt+T via RegisterHotKey and pumps its messages."""

    HOTKEY_ID = 0xA11
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_NOREPEAT = 0x4000
    WM_HOTKEY = 0x0312
    VK_T = 0x54

    def __init__(self, callback):
        super().__init__(daemon=True, name="TitanAccessHotkey")
        self._callback = callback
        self._thread_id = 0
        self._stop = threading.Event()

    def run(self):
        import ctypes
        import ctypes.wintypes as wt
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        mods = self.MOD_CONTROL | self.MOD_SHIFT | self.MOD_ALT | self.MOD_NOREPEAT
        if not user32.RegisterHotKey(None, self.HOTKEY_ID, mods, self.VK_T):
            print("[TitanAccess] failed to register Ctrl+Shift+Alt+T hotkey")
            return
        print("[TitanAccess] hotkey Ctrl+Shift+Alt+T registered")
        msg = wt.MSG()
        try:
            while not self._stop.is_set():
                r = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if r == 0 or r == -1:
                    break
                if msg.message == self.WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                    try:
                        self._callback()
                    except Exception as e:
                        print(f"[TitanAccess] hotkey callback error: {e}")
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            try:
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
        # Auto-start the reader if it was left enabled (the settings checkbox /
        # the hotkey persist this under General/Enabled).
        try:
            from titan_access.settings_store import get_settings
            if get_settings().enabled:
                print("[TitanAccess] auto-starting (enabled in settings)")
                start_reader()
        except Exception as e:
            print(f"[TitanAccess] auto-start check failed: {e}")
        print("[TitanAccess] ready (press Ctrl+Shift+Alt+T to toggle the reader)")
    except Exception as e:
        print(f"[TitanAccess] initialize error: {e}")
        import traceback
        traceback.print_exc()


def shutdown():
    """Called by the TCE ComponentManager on shutdown."""
    try:
        print("[TitanAccess] shutting down component...")
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
    print("Ctrl+Shift+Alt+T toggles. Ctrl+C to quit.")
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


if __name__ == "__main__":
    _standalone()
