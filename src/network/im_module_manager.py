"""Titan IM external module manager.

Loads communicator modules from data/titanIM_modules/ directory.
Each module has __im.TCE config and init.py with open(parent_frame) function.
Automatically injects unified TitanIM Sound API, local translations and a
namespaced configuration helper into every loaded module.
"""
import os
import sys
import time
import threading
import gettext as _gettext
import configparser
import importlib.util

from src.network.titanim_sound_api import TitanIMSoundAPI
from src.platform_utils import get_base_path, discover_data_entries

# Shared sound API instance for all modules
_sound_api = TitanIMSoundAPI()


class IMModuleConfig:
    """Namespaced load/save helper for the encrypted titan.IM file.

    Each Titan IM module gets its own slice of titan.IM keyed by namespace
    (its folder name). The whole file is read on every load/save so other
    modules' data (telegram, eltenlink, teamtalk, ...) is preserved.
    Modules use it as `config.load()` / `config.save({...})` and never need
    to know the encryption key or the file path.
    """

    def __init__(self, namespace):
        self.namespace = namespace

    def _read_all(self):
        try:
            from src.settings.titan_im_config import load_titan_im_config
            return load_titan_im_config() or {}
        except Exception as exc:
            print(f"[IM Modules] config.load_all failed for "
                  f"{self.namespace}: {exc}")
            return {}

    def _write_all(self, data):
        try:
            from src.settings.titan_im_config import save_titan_im_config
            return bool(save_titan_im_config(data))
        except Exception as exc:
            print(f"[IM Modules] config.save_all failed for "
                  f"{self.namespace}: {exc}")
            return False

    def load(self):
        """Return this module's config slice (an empty dict if missing)."""
        all_config = self._read_all()
        slice_data = all_config.get(self.namespace, {})
        return slice_data if isinstance(slice_data, dict) else {}

    def save(self, data):
        """Persist this module's slice without disturbing other modules."""
        if not isinstance(data, dict):
            print(f"[IM Modules] config.save({self.namespace}) "
                  f"requires a dict, got {type(data).__name__}")
            return False
        all_config = self._read_all()
        all_config[self.namespace] = data
        return self._write_all(all_config)

    def get(self, key, default=None):
        return self.load().get(key, default)

    def set(self, key, value):
        data = self.load()
        data[key] = value
        return self.save(data)

    def update(self, **kwargs):
        data = self.load()
        data.update(kwargs)
        return self.save(data)


class IMModuleUI:
    """Coalescing main-thread dispatcher injected into every IM module as
    `ui`.

    IM modules run in-process and share Titan's single wx event loop. A
    module with a background polling/network thread that calls wx.CallAfter
    once per incoming event floods that shared loop on a busy server and
    freezes ALL of Titan (this is exactly what froze the app via the
    TeamTalk module's per-event tree rebuilds).

    `ui.request(key, callback)` collapses a burst of requests sharing the
    same `key` into at most one `callback` call per `interval` seconds,
    always run on the wx main thread. Crucially, a whole burst posts only
    ONE wx.CallAfter, so the event loop is never flooded no matter how fast
    the module's thread produces events.

    Usage from a module's background thread:
        self.ui.request("tree", self._rebuild_tree)
        self.ui.request(f"user:{uid}", lambda: self._update_user(uid))

    The most recent callback registered for a key before it fires is the
    one that runs. For a plain one-shot main-thread call use ui.call().
    """

    def __init__(self, namespace, interval=0.25):
        self.namespace = namespace
        self.interval = interval
        self._lock = threading.Lock()
        self._pending = {}        # key -> callback
        self._scheduled = False   # a flush is already on its way

    def request(self, key, callback):
        """Schedule `callback` on the wx main thread, coalesced per `key`.

        Safe to call from any thread. A burst of requests for the same key
        results in a single call to the most recently registered callback.
        """
        with self._lock:
            self._pending[key] = callback
            if self._scheduled:
                return
            self._scheduled = True
        # Exactly ONE wx.CallAfter per debounce window - this is what keeps
        # the shared event loop from being flooded.
        try:
            import wx
            wx.CallAfter(self._arm)
        except Exception:
            # wx unavailable - run inline so the update is not lost.
            with self._lock:
                self._scheduled = False
            self._flush()

    def call(self, callback):
        """Run `callback` once on the wx main thread (uncoalesced).

        Thin wrapper over wx.CallAfter for modules that just need a single
        one-shot marshal and do not have a burst to collapse.
        """
        try:
            import wx
            wx.CallAfter(callback)
        except Exception:
            try:
                callback()
            except Exception:
                pass

    def _arm(self):
        # Main thread: now it is safe to create a wx timer for the window.
        try:
            import wx
            wx.CallLater(int(self.interval * 1000), self._flush)
        except Exception:
            self._flush()

    def _flush(self):
        # Main thread: run every coalesced callback collected this window.
        with self._lock:
            pending = self._pending
            self._pending = {}
            self._scheduled = False
        for key, callback in pending.items():
            try:
                callback()
            except Exception as exc:
                print(f"[IM Modules] ui.request callback for "
                      f"{self.namespace}:{key} failed: {exc}")


class _MainThreadWatchdog:
    """Detects when the shared wx main thread stops processing events.

    IM modules share Titan's single wx event loop, so a module that floods
    wx.CallAfter (or blocks the main thread any other way) freezes the whole
    application. This watchdog cannot *prevent* that, but it turns a silent
    total freeze into a logged, attributable event: a daemon thread
    periodically posts a ping via wx.CallAfter and measures how long the
    main thread takes to run it. A stall is reported once per episode,
    naming the IM modules currently open as the likely culprit.
    """

    STALL_SECONDS = 5.0      # main thread considered frozen past this
    CHECK_INTERVAL = 2.0     # gap between pings while responsive

    def __init__(self, manager):
        self._manager = manager
        self._thread = None
        self._started = False
        self._pong = threading.Event()
        self._stall_reported = False

    def start(self):
        """Start the watchdog thread once. Safe to call repeatedly."""
        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(
            target=self._loop, name="IMModuleWatchdog", daemon=True)
        self._thread.start()

    def _ping_target(self):
        # Runs on the wx main thread - its execution latency is the metric.
        self._pong.set()

    def _loop(self):
        try:
            import wx
        except Exception:
            return
        while True:
            self._pong.clear()
            try:
                wx.CallAfter(self._ping_target)
            except Exception:
                # wx no longer usable (app shutting down) - stop quietly.
                return
            if self._pong.wait(self.STALL_SECONDS):
                if self._stall_reported:
                    self._stall_reported = False
                    print("[IM Modules] wx main thread is responsive "
                          "again - Titan recovered from the freeze.")
                time.sleep(self.CHECK_INTERVAL)
            elif not self._stall_reported:
                self._stall_reported = True
                suspects = self._manager.get_opened_module_names()
                suspect_text = ", ".join(suspects) if suspects \
                    else "none recorded"
                print(f"[IM Modules] WARNING: wx main thread unresponsive "
                      f"for over {self.STALL_SECONDS:.0f}s - Titan is "
                      f"frozen. Open IM modules (likely culprit): "
                      f"{suspect_text}. A module's background thread is "
                      f"probably flooding wx.CallAfter - it should use "
                      f"the injected 'ui.request(...)' dispatcher instead.")
            # If still stalled and already reported, just loop: the next
            # _pong.wait(STALL_SECONDS) blocks ~5s, so there is no spam.


# Lazily created hidden wx host frame used as fallback parent when the
# caller does not supply one. This lets IM modules work from any TCE
# entry point - main GUI, Invisible UI, Klango mode, launcher mode - even
# when no top-level window is currently available.
_fallback_parent = None


def _apply_skin_to_new_top_windows(before_ids=None):
    """Apply Titan skin to top-level windows opened after a module call."""
    try:
        import wx
        from src.titan_core.skin_manager import apply_skin_to_window
    except Exception:
        return

    before_ids = before_ids or set()

    def _apply_recursive(window):
        try:
            apply_skin_to_window(window)
        except Exception:
            return
        for child in window.GetChildren():
            _apply_recursive(child)

    try:
        for win in wx.GetTopLevelWindows():
            try:
                if not win or not bool(win):
                    continue
                if id(win) in before_ids:
                    continue
                _apply_recursive(win)
            except Exception:
                continue
    except Exception:
        pass


def _resolve_parent(parent_frame):
    """Return a usable wx parent, falling back to a hidden host frame.

    Order of preference:
      1. The caller-supplied parent, if it's a live wx.Window.
      2. The first visible top-level wx window (main GUI, Klango frame,
         launcher window, ...).
      3. A lazily-created hidden host frame owned by this module.

    IM modules typically call parent.GetScreenPosition() or use the
    parent for ShowModal; with a None parent they can crash or display
    dialogs off-screen. This helper centralises the fallback logic so
    every caller benefits without having to plumb a parent themselves.
    """
    global _fallback_parent
    try:
        import wx
    except Exception:
        return parent_frame

    # 1. Caller-supplied parent if it's alive.
    if parent_frame is not None:
        try:
            if bool(parent_frame):
                return parent_frame
        except Exception:
            pass

    # 2. Any currently-visible top-level window.
    try:
        for w in wx.GetTopLevelWindows():
            try:
                if w and w is not _fallback_parent and w.IsShown():
                    return w
            except Exception:
                continue
    except Exception:
        pass

    # 3. Lazy hidden host frame.
    if _fallback_parent is None:
        try:
            _fallback_parent = wx.Frame(None, title="TCE IM Host",
                                        size=(1, 1))
            _fallback_parent.Move(-10000, -10000)
            _fallback_parent.Hide()
        except Exception as e:
            print(f"[IM Modules] Failed to create fallback parent: {e}")
            return None
    return _fallback_parent


class TitanIMModuleManager:
    def __init__(self):
        self.modules = []  # list of dicts: {name, id, module, path}
        # Module ids that have been opened this session, most recent last.
        # Used by the watchdog to attribute a main-thread stall.
        self._opened_module_ids = []
        self._watchdog = _MainThreadWatchdog(self)

    def load_modules(self):
        """Scan data/titanIM_modules/ across bundled + user overlay and load
        all valid modules. User-overlay modules win on folder-name collision."""
        self.modules = []
        entries = discover_data_entries('titanIM_modules')

        if not entries:
            return

        for entry, module_path in entries.items():
            if not os.path.isdir(module_path):
                continue

            config_file = os.path.join(module_path, "__im.TCE")
            if not os.path.isfile(config_file):
                continue

            try:
                config = configparser.ConfigParser()
                config.read(config_file, encoding="utf-8")

                if not config.has_section("im_module"):
                    continue

                status = config.get("im_module", "status", fallback="0")
                if status != "0":
                    continue

                name = config.get("im_module", "name", fallback=entry)
                module_id = entry

                init_file = os.path.join(module_path, "init.py")
                if not os.path.isfile(init_file):
                    continue

                # Add module's library paths to sys.path for bundled dependencies
                # Config: libs = lib, vendor (comma-separated, relative to module dir)
                # Default: lib/ if exists, plus the module directory itself
                lib_paths_str = config.get("im_module", "libs", fallback="")
                if lib_paths_str.strip():
                    lib_dirs = [d.strip() for d in lib_paths_str.split(",") if d.strip()]
                else:
                    lib_dirs = ["lib"]
                for ld in lib_dirs:
                    full_lib = os.path.join(module_path, ld)
                    if os.path.isdir(full_lib) and full_lib not in sys.path:
                        sys.path.insert(0, full_lib)
                if module_path not in sys.path:
                    sys.path.insert(0, module_path)

                spec = importlib.util.spec_from_file_location(
                    f"titanIM_modules.{module_id}", init_file)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mod

                # Inject unified Sound API before executing module code
                # so module can use sounds at import time if needed
                mod.sounds = _sound_api

                # Inject the Buffer System API (category bound to this module),
                # so an IM module can publish chat/PM/notification buffers into
                # the global review system: mod.buffers.push("chat", text, ...).
                try:
                    from src.buffers import buffer_bus
                    mod.buffers = buffer_bus.make_module_api(module_id)
                except Exception as _be:
                    print(f"[IMModule] buffer API injection failed: {_be}")

                # Inject namespaced config helper. Modules store/restore
                # their own settings via mod.config.load() / mod.config.save()
                # without ever touching the encryption key behind titan.IM.
                mod.config = IMModuleConfig(module_id)

                # Inject the coalescing main-thread dispatcher. Modules with
                # a background poll/network thread MUST push UI updates
                # through mod.ui.request(...) instead of raw wx.CallAfter -
                # see the IMModuleUI docstring. Stops a module from flooding
                # the shared wx event loop and freezing Titan.
                mod.ui = IMModuleUI(module_id)

                # Inject local translations from module's own languages/ dir
                module_locale_dir = os.path.join(module_path, 'languages')
                if os.path.isdir(module_locale_dir):
                    try:
                        from src.settings.settings import get_setting
                        lang = get_setting('language', 'pl')
                        trans = _gettext.translation(module_id, module_locale_dir, languages=[lang], fallback=True)
                        mod._ = trans.gettext
                    except Exception:
                        mod._ = lambda x: x
                else:
                    mod._ = lambda x: x

                spec.loader.exec_module(mod)

                self.modules.append({
                    "name": name,
                    "id": module_id,
                    "module": mod,
                    "path": module_path
                })
                print(f"[IM Modules] Loaded: {name} ({module_id})")

            except Exception as e:
                print(f"[IM Modules] Failed to load {entry}: {e}")

    def get_module_names(self):
        """Return list of module display names."""
        return [info["name"] for info in self.modules]

    def open_module(self, name_or_id, parent_frame=None):
        """Open module by name or id. Returns True if found and opened.

        parent_frame may be None - a fallback hidden host frame is used
        so IM modules can be launched from frontends that don't have a
        visible top-level window (Invisible UI, launcher mode without
        the main GUI, etc.).
        """
        for info in self.modules:
            if info["id"] == name_or_id or info["name"] == name_or_id:
                try:
                    before_ids = set()
                    try:
                        import wx
                        before_ids = {id(w) for w in wx.GetTopLevelWindows() if w}
                    except Exception:
                        pass

                    effective_parent = _resolve_parent(parent_frame)
                    info["module"].open(effective_parent)
                    _apply_skin_to_new_top_windows(before_ids)
                    # Record as opened (most recent last) and make sure the
                    # main-thread watchdog is running now that a module is
                    # in use.
                    if info["id"] in self._opened_module_ids:
                        self._opened_module_ids.remove(info["id"])
                    self._opened_module_ids.append(info["id"])
                    self._watchdog.start()
                    return True
                except Exception as e:
                    print(f"[IM Modules] Error opening {info['name']}: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
        return False

    def get_opened_module_names(self):
        """Display names of IM modules opened this session, most recent last.

        Used by the main-thread watchdog to attribute a freeze to the
        likely culprit module.
        """
        names = []
        for module_id in self._opened_module_ids:
            for info in self.modules:
                if info["id"] == module_id:
                    names.append(info["name"])
                    break
        return names

    def get_status_text(self, name_or_id):
        """Return optional status suffix from module, or empty string."""
        for info in self.modules:
            if info["id"] == name_or_id or info["name"] == name_or_id:
                try:
                    if hasattr(info["module"], "get_status_text"):
                        return info["module"].get_status_text()
                except Exception:
                    pass
        return ""


im_module_manager = TitanIMModuleManager()
