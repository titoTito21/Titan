# -*- coding: utf-8 -*-
"""NVDA controller server for Titan Access.

Lets any application built against the unmodified ``nvdaControllerClient*.dll``
(and, importantly, ``accessible_output3``'s NVDA backend -- which is how the TCE
launcher's ``speak_sr_only`` / ``is_screen_reader_running`` detect a reader)
drive Titan Access exactly as they would drive NVDA: ``speakText`` /
``cancelSpeech`` / ``brailleMessage`` / ``testIfRunning``.

All of the MS-RPC plumbing lives in the small native helper
``titan_access_helper.dll`` (built from ``helper/`` -- see ``helper/README.md``).
This module just loads it, hands it three callbacks, and starts / stops it.
When the DLL is missing (not yet compiled) every method is a safe no-op, so the
reader runs fine without it -- only this NVDA-compatibility bridge is disabled.

The helper registers the RPC endpoint NVDA itself uses
(``NvdaCtlr.<session>.<desktop>`` over ``ncalrpc``); if real NVDA is already
running it owns the endpoint and our registration simply backs off.
"""

import ctypes
import os
import sys

_IS_WINDOWS = sys.platform.startswith("win")

# Candidate DLL names / locations, searched in order.
_DLL_NAMES = ("titan_access_helper.dll",)
_COMPONENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SEARCH_DIRS = (
    _COMPONENT_DIR,
    os.path.join(_COMPONENT_DIR, "helper"),
    os.path.join(_COMPONENT_DIR, "lib"),
)


def _find_dll():
    for d in _SEARCH_DIRS:
        for name in _DLL_NAMES:
            path = os.path.join(d, name)
            if os.path.isfile(path):
                return path
    return None


class NvdaControllerServer:
    """Loads the helper DLL and routes NVDA-controller calls to the engine."""

    def __init__(self, engine):
        self.engine = engine
        self._dll = None
        self._started = False
        self._get_pid = None
        # PIDs of processes that have driven us through the controller; the
        # engine uses this to play its "in a controller app" earcons.
        self.client_pids = set()
        # Strong refs to the ctypes callbacks -- if these are GC'd the native
        # side calls freed memory and crashes the host process.
        self._cb_speak = None
        self._cb_cancel = None
        self._cb_braille = None

    # ------------------------------------------------------------------ #
    def start(self):
        """Load + start the server. Returns self (always) so callers can chain;
        a missing DLL or any error just leaves the bridge inactive."""
        if not _IS_WINDOWS or self._started:
            return self
        try:
            if not self.engine.settings.get_bool(
                    "General", "NvdaControllerServer", True):
                return self
        except Exception:
            pass

        path = _find_dll()
        if path is None:
            print("[TitanAccess] NVDA controller helper DLL not found "
                  "(build helper/build.bat to enable NVDA-compatible speech)")
            return self

        try:
            dll = ctypes.WinDLL(path)
        except Exception as e:
            print(f"[TitanAccess] could not load {os.path.basename(path)}: {e}")
            return self

        # Callback prototypes (stdcall, matching the C typedefs).
        speak_t = ctypes.WINFUNCTYPE(None, ctypes.c_wchar_p)
        void_t = ctypes.WINFUNCTYPE(None)
        braille_t = ctypes.WINFUNCTYPE(None, ctypes.c_wchar_p)

        self._cb_speak = speak_t(self._on_speak)
        self._cb_cancel = void_t(self._on_cancel)
        self._cb_braille = braille_t(self._on_braille)

        try:
            dll.TitanAccessHelper_start.argtypes = [speak_t, void_t, braille_t]
            dll.TitanAccessHelper_start.restype = ctypes.c_int
            dll.TitanAccessHelper_stop.argtypes = []
            dll.TitanAccessHelper_stop.restype = None
            try:
                dll.TitanAccessHelper_lastClientPid.argtypes = []
                dll.TitanAccessHelper_lastClientPid.restype = ctypes.c_ulong
                self._get_pid = dll.TitanAccessHelper_lastClientPid
            except Exception:
                self._get_pid = None
            rc = dll.TitanAccessHelper_start(
                self._cb_speak, self._cb_cancel, self._cb_braille)
        except Exception as e:
            print(f"[TitanAccess] NVDA controller start error: {e}")
            return self

        if rc != 0:
            print(f"[TitanAccess] NVDA controller server not started (rc={rc}); "
                  f"another controller (NVDA?) may already own the endpoint")
            return self

        self._dll = dll
        self._started = True
        print("[TitanAccess] NVDA controller server active "
              "(apps using nvdaControllerClient.dll now speak through Titan Access)")
        # If NVDA is also running it OWNS the single ncalrpc controller endpoint,
        # so external apps reach NVDA, not us -- make that diagnosable.
        try:
            import psutil
            if any((p.name() or "").lower() == "nvda.exe"
                   for p in psutil.process_iter(["name"])):
                print("[TitanAccess] WARNING: NVDA is running -- it owns the NVDA "
                      "controller endpoint, so other apps speak through NVDA, not "
                      "Titan Access. Close NVDA to let Titan Access handle them.")
        except Exception:
            pass
        return self

    def stop(self):
        if self._dll is not None and self._started:
            try:
                self._dll.TitanAccessHelper_stop()
            except Exception as e:
                print(f"[TitanAccess] NVDA controller stop error: {e}")
        self._started = False
        self._dll = None

    # ------------------------------------------------------------------ #
    # RPC callbacks (invoked on rpcrt4 worker threads)
    # ------------------------------------------------------------------ #
    def _note_client(self):
        if self._get_pid is not None:
            try:
                pid = int(self._get_pid())
                if pid:
                    self.client_pids.add(pid)
            except Exception:
                pass

    def _on_speak(self, text):
        self._note_client()
        try:
            if text:
                self.engine.speak(text, interrupt=True)
        except Exception as e:
            print(f"[TitanAccess] controller speakText error: {e}")

    def _on_cancel(self):
        self._note_client()
        try:
            if self.engine.speech is not None:
                self.engine.speech.stop()
        except Exception as e:
            print(f"[TitanAccess] controller cancelSpeech error: {e}")

    def _on_braille(self, message):
        self._note_client()
        # No braille display support yet; speak it so the message is not lost.
        try:
            if message:
                self.engine.speak(message, interrupt=False)
        except Exception as e:
            print(f"[TitanAccess] controller brailleMessage error: {e}")
