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


#: The executables real NVDA runs as (installed, portable, with and without
#: UI Access). ``nvda_probe*.exe`` - this component's own probes - are not.
NVDA_PROCESSES = frozenset(("nvda.exe", "nvda_uiaccess.exe",
                            "nvda_nouiaccess.exe"))
#: How often the guard looks for NVDA starting. NVDA reaches its "is NVDA
#: already running" check after importing a good part of itself - several
#: hundred milliseconds after its process appears - so a tenth of a second
#: is in time with room to spare. A look is `psutil.pids()` (~0.03 ms) and
#: a name only for a pid not seen before.
GUARD_POLL_S = 0.1
#: How long NVDA must have been gone before the NVDA window comes back.
WINDOW_BACK_AFTER_S = 3.0
#: How long NVDA must have been gone before the endpoint is taken over:
#: NVDA restarting (NVDA+Q, an add-on installed) is an exit and a start a
#: moment apart, and taking the endpoint in between would leave the NVDA
#: that comes back without its own controller for the whole session.
ENDPOINT_AFTER_S = 10.0
RETRY_EVERY_S = 5.0


class _NvdaProcesses:
    """Which of the machine's processes are NVDA, kept up to date cheaply."""

    def __init__(self):
        self._known = {}            # pid -> is NVDA
        try:
            import psutil
            self._psutil = psutil
        except Exception:                            # noqa: BLE001
            self._psutil = None

    def _name_of(self, pid):
        try:
            return (self._psutil.Process(pid).name() or "").lower()
        except Exception:                            # noqa: BLE001
            return ""

    def _snapshot(self):
        """``{pid: name}`` of every process, without psutil (Toolhelp)."""
        found = {}
        try:
            import ctypes.wintypes as wt

            class PROCESSENTRY32W(ctypes.Structure):
                _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                            ("th32ProcessID", wt.DWORD),
                            ("th32DefaultHeapID", ctypes.c_void_p),
                            ("th32ModuleID", wt.DWORD),
                            ("cntThreads", wt.DWORD),
                            ("th32ParentProcessID", wt.DWORD),
                            ("pcPriClassBase", ctypes.c_long),
                            ("dwFlags", wt.DWORD),
                            ("szExeFile", ctypes.c_wchar * 260)]
            k32 = ctypes.windll.kernel32
            k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
            snap = k32.CreateToolhelp32Snapshot(0x2, 0)
            if not snap or snap == ctypes.c_void_p(-1).value:
                return found
            try:
                entry = PROCESSENTRY32W()
                entry.dwSize = ctypes.sizeof(entry)
                ok = k32.Process32FirstW(ctypes.c_void_p(snap),
                                         ctypes.byref(entry))
                while ok:
                    found[int(entry.th32ProcessID)] = entry.szExeFile.lower()
                    ok = k32.Process32NextW(ctypes.c_void_p(snap),
                                            ctypes.byref(entry))
            finally:
                k32.CloseHandle(ctypes.c_void_p(snap))
        except Exception:                            # noqa: BLE001
            pass
        return found

    def running(self):
        """True while any NVDA process is alive."""
        if self._psutil is None:
            return any(name in NVDA_PROCESSES
                       for name in self._snapshot().values())
        try:
            pids = set(self._psutil.pids())
        except Exception:                            # noqa: BLE001
            return False
        for gone in [pid for pid in self._known if pid not in pids]:
            del self._known[gone]
        for pid in pids:
            if pid not in self._known:
                self._known[pid] = self._name_of(pid) in NVDA_PROCESSES
        return any(self._known.values())


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
    @staticmethod
    def wanted(settings):
        """Whether the reader should hold NVDA's controller endpoint.

        Not while "Mute outside TCE" is on: the endpoint is ONE name for
        the whole session, and whoever holds it hears every program that
        speaks through nvdaControllerClient - a game outside TCE included.
        A reader that keeps quiet outside TCE holding it would make those
        programs silent, so the system's own reader (NVDA) keeps it."""
        try:
            if not settings.get_bool("General", "NvdaControllerServer", True):
                return False
            if settings.mute_outside_tce:
                return False
        except Exception:
            pass
        return True

    def start(self):
        """Load + start the server. Returns self (always) so callers can chain;
        a missing DLL or any error just leaves the bridge inactive."""
        if not _IS_WINDOWS or self._started:
            return self
        if not self.wanted(self.engine.settings):
            return self

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
            try:
                dll.TitanAccessHelper_setNvdaWindow.argtypes = [ctypes.c_int]
                dll.TitanAccessHelper_setNvdaWindow.restype = ctypes.c_int
            except Exception:
                pass
            for name, restype in (("TitanAccessHelper_ownsEndpoint", ctypes.c_int),
                                  ("TitanAccessHelper_hasNvdaWindow", ctypes.c_int),
                                  ("TitanAccessHelper_retryEndpoint", ctypes.c_int),
                                  ("TitanAccessHelper_callCount", ctypes.c_ulong)):
                try:
                    getattr(dll, name).argtypes = []
                    getattr(dll, name).restype = restype
                except Exception:
                    pass
            self._nvda = _NvdaProcesses()
            if self._nvda.running():
                # NVDA is here (or starting): no NVDA window of ours at all.
                self._set_window(dll, False)
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
        self._start_watch()
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

    def _set_window(self, dll, show):
        """Put the hidden NVDA window up or take it down.

        A helper built before `TitanAccessHelper_setNvdaWindow` existed can
        still have its window closed (by message); it cannot be told to put
        it back, which only costs Tolk-based games the window until the
        reader is next started."""
        try:
            return bool(dll.TitanAccessHelper_setNvdaWindow(1 if show else 0))
        except AttributeError:
            pass
        except Exception:                            # noqa: BLE001
            return False
        if show:
            return False
        try:
            user32 = ctypes.windll.user32
            user32.FindWindowW.restype = ctypes.c_void_p
            hwnd = user32.FindWindowW("wxWindowClassNR", "NVDA")
            pid = ctypes.c_ulong(0)
            if hwnd:
                user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd),
                                                ctypes.byref(pid))
                if pid.value == os.getpid():
                    user32.PostMessageW(ctypes.c_void_p(hwnd), 0x0010, 0, 0)
        except Exception:                            # noqa: BLE001
            pass
        return False

    def _start_watch(self):
        """Keep out of real NVDA's way, and take the endpoint once it is gone.

        **Real NVDA kills the process holding an "NVDA" window.** Starting,
        NVDA looks for ``FindWindow("wxWindowClassNR", "NVDA")`` - the very
        window this bridge keeps for Tolk - takes it for an NVDA already
        running, posts it WM_QUIT, waits for its PROCESS to exit and then
        calls TerminateProcess on it (read out of nvda.exe:
        `terminateRunningNVDA`). That process is Titan: starting or
        restarting NVDA while Titan Access was running froze Titan for the
        wait and then ended it - or NVDA gave up on its own start. So the
        window is taken down the moment an NVDA process appears and put
        back only once NVDA has been gone a while; and the endpoint is not
        taken over while NVDA is merely restarting.
        """
        import threading
        if self._watch_thread is not None and self._watch_thread.is_alive():
            return
        self._watch_stop = threading.Event()
        stop = self._watch_stop
        nvda = getattr(self, "_nvda", None) or _NvdaProcesses()

        def _watch():
            import time
            window_wanted = not nvda.running()
            gone_since = None if not window_wanted else time.monotonic()
            last_retry = 0.0
            while not stop.wait(GUARD_POLL_S):
                dll = self._dll
                if dll is None or not self._started:
                    return
                now = time.monotonic()
                try:
                    present = nvda.running()
                except Exception:                    # noqa: BLE001
                    present = False
                if present:
                    gone_since = None
                    if window_wanted:
                        window_wanted = False
                        self._set_window(dll, False)
                        print("[TitanAccess] NVDA is starting - the NVDA "
                              "window is taken down, or NVDA would end Titan")
                    continue
                if gone_since is None:
                    gone_since = now
                away = now - gone_since
                if not window_wanted and away >= WINDOW_BACK_AFTER_S:
                    window_wanted = True
                    self._set_window(dll, True)
                if not self._owns_endpoint and away >= ENDPOINT_AFTER_S \
                        and now - last_retry >= RETRY_EVERY_S:
                    last_retry = now
                    try:
                        if dll.TitanAccessHelper_retryEndpoint():
                            self._owns_endpoint = True
                            print("[TitanAccess] NVDA controller server active "
                                  "-- the endpoint was released and Titan "
                                  "Access has taken it over")
                    except Exception:                # noqa: BLE001
                        pass

        self._watch_thread = threading.Thread(target=_watch, daemon=True,
                                              name="TitanAccessCtlrWatch")
        self._watch_thread.start()

    def has_nvda_window(self) -> bool:
        """True while the hidden ``wxWindowClassNR`` / "NVDA" window is up.

        Tolk (most audio games, both bitnesses) looks for that window before
        it asks the controller anything; without it the game reports no
        screen reader at all and the endpoint is never called."""
        if self._dll is None:
            return False
        try:
            return bool(self._dll.TitanAccessHelper_hasNvdaWindow())
        except Exception:
            return False

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
            if served > 0 and not self.has_nvda_window():
                # The endpoint answers, but Tolk asks for NVDA's window first
                # and would still report no screen reader.
                results.append((bits, False,
                                "the controller answers, but the hidden NVDA "
                                "window is missing, so Tolk-based programs "
                                "will not find Titan Access: " + line))
            elif served > 0:
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
        # Braille, not speech. Tolk_Output - what most audio games call - sends
        # every line to speakText AND brailleMessage, so speaking this as well
        # said every line of a game twice. Real NVDA puts it on the display.
        try:
            if message:
                from . import braille
                braille.show_text(message)
        except Exception as e:
            print(f"[TitanAccess] controller brailleMessage error: {e}")
