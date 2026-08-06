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
(``NvdaCtlr.<session>.<desktop>`` over ``ncalrpc``).

**That endpoint is one name, and only one process can own it.** Whoever
registers it first receives every application's controller calls; everybody else
receives none. That is the whole reason this bridge can appear to "work with
64-bit applications but not with 32-bit ones": Titan's own 64-bit code speaks
through the engine directly and never goes near RPC, so only a separate
application -- very often a 32-bit one -- exercises this path at all. If another
controller (real NVDA, or an earlier Titan that has not exited) holds the
endpoint, that application's speech goes there instead, and the bridge looks
broken for reasons that have nothing to do with bitness. The RPC layer itself is
bitness-agnostic: 32-bit and 64-bit clients both reach the helper, which
``helper/nvda_probe32.exe`` / ``nvda_probe64.exe`` prove on demand (see
:meth:`NvdaControllerServer.self_test`).

So this module reports honestly whether we actually own the endpoint, keeps
trying to take it over while somebody else does (closing NVDA is then enough --
no Titan restart), and can verify the whole path from a real process of each
bitness.
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
        self._owns_endpoint = False
        self._watch_thread = None
        self._watch_stop = None
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
            # Newer helper exports; an older DLL simply lacks them.
            for name, restype in (("TitanAccessHelper_ownsEndpoint", ctypes.c_int),
                                  ("TitanAccessHelper_retryEndpoint", ctypes.c_int),
                                  ("TitanAccessHelper_callCount", ctypes.c_ulong)):
                try:
                    getattr(dll, name).argtypes = []
                    getattr(dll, name).restype = restype
                except Exception:
                    pass
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
        self._owns_endpoint = self._read_owns()
        if self._owns_endpoint:
            print("[TitanAccess] NVDA controller server active -- applications "
                  "using nvdaControllerClient32.dll or ...64.dll (either bitness) "
                  "now speak through Titan Access")
        else:
            # Another controller holds the endpoint, so applications reach IT,
            # not us. Reporting "active" here is what turned a plain conflict
            # into "the bridge does not work with my program".
            print("[TitanAccess] NVDA controller: another screen reader owns the "
                  "controller endpoint, so applications speak through it, not "
                  "Titan Access" + self._who_owns())
            self._start_watch()
        return self

    # ------------------------------------------------------------------ #
    # Endpoint ownership
    # ------------------------------------------------------------------ #
    @property
    def owns_endpoint(self) -> bool:
        """True when applications' controller calls actually arrive here."""
        return bool(self._owns_endpoint)

    def _read_owns(self) -> bool:
        if self._dll is None:
            return False
        try:
            return bool(self._dll.TitanAccessHelper_ownsEndpoint())
        except Exception:
            return True     # an older helper cannot tell us; assume the best

    @staticmethod
    def _who_owns() -> str:
        """A parenthetical naming the likely owner, when one can be found."""
        try:
            import psutil
            for proc in psutil.process_iter(["name"]):
                if (proc.info.get("name") or "").lower() == "nvda.exe":
                    return (" (NVDA is running -- close it and Titan Access takes "
                            "the endpoint over by itself)")
        except Exception:
            pass
        return ""

    def _start_watch(self):
        """Take the endpoint over the moment its current owner lets go.

        A slow poll, running only while we do NOT own it, so a user who closes
        the other screen reader gets a working bridge without restarting Titan.
        """
        import threading
        if self._watch_thread is not None and self._watch_thread.is_alive():
            return
        self._watch_stop = threading.Event()
        stop = self._watch_stop

        def _watch():
            while not stop.wait(5.0):
                if self._dll is None or not self._started:
                    return
                try:
                    if self._dll.TitanAccessHelper_retryEndpoint():
                        self._owns_endpoint = True
                        print("[TitanAccess] NVDA controller server active -- the "
                              "endpoint was released and Titan Access has taken "
                              "it over (applications of either bitness reach us "
                              "now)")
                        return
                except Exception:
                    return

        self._watch_thread = threading.Thread(target=_watch, daemon=True,
                                              name="TitanAccessCtlrWatch")
        self._watch_thread.start()

    def call_count(self) -> int:
        """How many controller calls this process has served."""
        if self._dll is None:
            return 0
        try:
            return int(self._dll.TitanAccessHelper_callCount())
        except Exception:
            return 0

    # ------------------------------------------------------------------ #
    # Self-test (both bitnesses, from real processes)
    # ------------------------------------------------------------------ #
    def self_test(self, bitnesses=(64, 32)):
        """Prove -- or disprove -- that applications reach us, per bitness.

        Runs ``helper/nvda_probe<bits>.exe``, which binds to the controller
        endpoint and calls it exactly as an application does, then checks
        whether the call arrived HERE (the helper's own counter) rather than at
        some other screen reader. This is the only honest answer to "does it
        work with 32-bit programs?": Titan is a 64-bit process and can never
        exercise the 32-bit client path in process.

        Returns a list of ``(bits, ok, detail)``.
        """
        import subprocess
        results = []
        for bits in bitnesses:
            probe = os.path.join(_COMPONENT_DIR, "helper", "nvda_probe%d.exe" % bits)
            if not os.path.isfile(probe):
                results.append((bits, False,
                                "probe not built (run helper/build.bat)"))
                continue
            before = self.call_count()
            try:
                out = subprocess.run(
                    [probe, "Titan Access %d bit self test" % bits],
                    capture_output=True, text=True, timeout=15,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                line = (out.stdout or "").strip() or (out.stderr or "").strip()
            except Exception as e:
                results.append((bits, False, "probe failed: %s" % e))
                continue
            served = self.call_count() - before
            if served > 0:
                results.append((bits, True, line))
            elif "1722" in line:
                results.append((bits, False,
                                "no screen reader is listening on the controller "
                                "endpoint: " + line))
            else:
                results.append((bits, False,
                                "answered by a DIFFERENT screen reader, not Titan "
                                "Access: " + line))
        return results

    def stop(self):
        if self._watch_stop is not None:
            self._watch_stop.set()
        if self._dll is not None and self._started:
            try:
                self._dll.TitanAccessHelper_stop()
            except Exception as e:
                print(f"[TitanAccess] NVDA controller stop error: {e}")
        self._started = False
        self._owns_endpoint = False
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
