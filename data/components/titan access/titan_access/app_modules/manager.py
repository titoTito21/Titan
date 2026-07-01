# -*- coding: utf-8 -*-
"""Application module manager.

Python port of ``ScreenReader/AppModules/AppModuleManager.cs`` (NVDA
``appModuleHandler``). Resolves the foreground process for each focus event and
delegates to the matching :class:`AppModuleBase`, caching the active module and
firing lose/gain transitions when the foreground application changes.

The engine calls :meth:`on_gain_focus` from ``engine.on_focus`` *before* it
announces the element, so :meth:`AppModuleBase.customize_object` can mutate the
:class:`AccessibleObject` in place and influence the announcement.
"""

import ctypes
import os

from titan_access.app_modules.explorer import ExplorerModule
from titan_access.app_modules.notepad import NotepadModule
from titan_access.app_modules.calculator import CalculatorModule
from titan_access.app_modules.tce import TCEModule
from titan_access.app_modules.chromium import ChromiumModule, EdgeModule
from titan_access.app_modules.firefox import FirefoxModule
from titan_access.app_modules.terminal import TerminalModule

# Module classes registered with the manager. Add new modules here.
_MODULE_CLASSES = (
    ExplorerModule, NotepadModule, CalculatorModule, TCEModule,
    ChromiumModule, EdgeModule, FirefoxModule, TerminalModule,
)


class AppModuleManager:
    """Selects and drives the active per-application module."""

    def __init__(self, engine):
        self.engine = engine
        # process name -> module instance
        self._modules = {}
        for cls in _MODULE_CLASSES:
            try:
                inst = cls(engine)
                # A module may serve several executables (e.g. the terminal
                # module handles cmd / powershell / putty / ...). It declares
                # them in ``process_names``; register the one instance under
                # each so the manager resolves it for any of them.
                names = getattr(cls, "process_names", None) or [inst.process_name]
                for name in names:
                    if name:
                        self._modules[name.lower()] = inst
            except Exception as e:
                print(f"[TitanAccess] app module init failed ({cls.__name__}): {e}")
        # External / downloaded modules (override built-ins for the same exe).
        try:
            from titan_access.app_modules.loader import load_external_modules
            self._modules.update(load_external_modules(engine))
        except Exception as e:
            print(f"[TitanAccess] external app module load failed: {e}")
        self._current = None
        self._current_process = None
        self._app_gesture_ids = []   # gesture action ids registered for the app

    # ==================================================================== #
    # Focus delegation
    # ==================================================================== #
    def on_gain_focus(self, obj):
        """Resolve the active module for ``obj`` and let it customise it."""
        process = self._process_for_object(obj)
        if process != self._current_process:
            self._switch_module(process, obj)
        if self._current is not None:
            try:
                self._current.customize_object(obj)
            except Exception as e:
                print(f"[TitanAccess] customize_object error "
                      f"({self._current_process}): {e}")
            try:
                self._current.on_gain_focus(obj)
            except Exception as e:
                print(f"[TitanAccess] on_gain_focus error "
                      f"({self._current_process}): {e}")

    def _switch_module(self, process, obj):
        if self._current is not None:
            try:
                self._current.on_lose_focus(obj)
            except Exception:
                pass
            self._unregister_app_gestures()
        self._current_process = process
        self._current = self._modules.get(process) if process else None
        if self._current is not None:
            self._register_app_gestures(self._current)

    def should_announce(self, obj):
        """False if the active module wants the standard announcement suppressed."""
        if self._current is None:
            return True
        try:
            return bool(self._current.should_announce(obj))
        except Exception:
            return True

    def handle_plain_key(self, vk, key_name, ctrl, alt, shift):
        """Let the active app module intercept a plain key. True = swallow.

        Resolves the module for the *current foreground* process even when no
        focus event has fired yet (a bare terminal fires no UIA focus changes),
        so the terminal review layer still receives keys."""
        module = self._current
        if module is None:
            process = self._process_for_object(None)
            if process != self._current_process:
                self._switch_module(process, None)
            module = self._current
        if module is None:
            return False
        try:
            return bool(module.handle_plain_key(vk, key_name, ctrl, alt, shift))
        except Exception as e:
            print(f"[TitanAccess] handle_plain_key error "
                  f"({self._current_process}): {e}")
            return False

    # ==================================================================== #
    # Per-application gestures
    # ==================================================================== #
    def _register_app_gestures(self, module):
        gestures = getattr(self.engine, "gestures", None)
        if gestures is None:
            return
        try:
            mapping = module.get_gestures() or {}
        except Exception as e:
            print(f"[TitanAccess] app gestures error ({module.process_name}): {e}")
            return
        for i, (spec, handler) in enumerate(mapping.items()):
            action_id = f"app:{module.process_name}:{i}"
            try:
                gestures.register(action_id, spec, handler)
                self._app_gesture_ids.append(action_id)
            except Exception as e:
                print(f"[TitanAccess] app gesture register error: {e}")

    def _unregister_app_gestures(self):
        gestures = getattr(self.engine, "gestures", None)
        if gestures is not None:
            for action_id in self._app_gesture_ids:
                try:
                    gestures.unregister(action_id)
                except Exception:
                    pass
        self._app_gesture_ids = []

    @property
    def current_module(self):
        return self._current

    def has_module_for(self, process_name):
        return bool(process_name) and process_name.lower() in self._modules

    # ==================================================================== #
    # Process resolution
    # ==================================================================== #
    def _process_for_object(self, obj):
        """Foreground process name (lower-case, no ``.exe``).

        The TCE process group -- the launcher and anything it spawned -- collapses
        to the synthetic key ``"tce"`` so the TCE app module sees one logical app
        (no enter/leave cue when moving between TCE-launched windows)."""
        pid = getattr(obj, "process_id", 0) if obj is not None else 0
        if not pid:
            pid = _foreground_pid()
        try:
            if pid and self.engine._pid_is_tce(pid):
                return "tce"
        except Exception:
            pass
        return _process_name_for_pid(pid) if pid else ""


# =========================================================================== #
# Win32 helpers (defensive; never raise)
# =========================================================================== #
def _foreground_pid() -> int:
    try:
        import ctypes.wintypes as wt
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = wt.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def _process_name_for_pid(pid: int) -> str:
    if not pid:
        return ""
    try:
        import ctypes.wintypes as wt
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        k = ctypes.windll.kernel32
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(512)
            size = wt.DWORD(512)
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.splitext(os.path.basename(buf.value))[0].lower()
        finally:
            k.CloseHandle(h)
    except Exception:
        pass
    return ""
