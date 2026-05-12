"""
TitanTTS Engine Registry
=========================
Central registry for discovering, loading, and managing TTS engines.

Scans data/titantts engines/ for engine folders containing:
  - __engine__.TCE  (INI config: [engine] name, status)
  - __engine__.py   (Python entry point with get_engine() factory)

Platform engines (eSpeak, SAPI5, etc.) are registered by StereoSpeech
as PlatformEngineProxy objects.
"""

import configparser
import os
import sys
import threading
import importlib.util as _importlib_util

from src.tts.base_engine import TitanTTSEngine


def _log(msg):
    """Write debug message to engine_registry log file."""
    try:
        if getattr(sys, 'frozen', False):
            log_path = os.path.join(os.path.dirname(sys.executable), 'engine_registry_debug.log')
        else:
            log_path = os.path.join(os.path.dirname(__file__), '..', '..', 'engine_registry_debug.log')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"{msg}\n")
    except Exception:
        pass


class PlatformEngineProxy(TitanTTSEngine):
    """
    Lightweight proxy for platform engines that still live inside StereoSpeech.

    These engines (eSpeak, SAPI5, macOS Speech, Speech Dispatcher) remain
    implemented in stereo_speech.py. This proxy provides metadata so the
    registry can list them alongside TitanTTS engines.

    The actual speech generation for platform engines is handled by
    StereoSpeech directly (not through this proxy).
    """

    def __init__(self, engine_id, engine_name, available=False):
        self.engine_id = engine_id
        self.engine_name = engine_name
        self.engine_category = 'platform'
        self.needs_lock_release = False
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, text, pitch_offset=0):
        return None

    def get_voices(self):
        return []

    def set_voice(self, voice_id):
        pass


def _get_engines_dir():
    """Return path to bundled data/titantts engines/ directory."""
    try:
        from src.platform_utils import get_base_path
        base = get_base_path()
        _log(f"[_get_engines_dir] get_base_path() = {base}")
    except ImportError as e:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        _log(f"[_get_engines_dir] ImportError fallback, base = {base}, error = {e}")
    result = os.path.join(base, 'data', 'titantts engines')
    _log(f"[_get_engines_dir] result = {result}, exists = {os.path.isdir(result)}")
    return result


def _iter_engine_folders():
    """Yield (folder_name, abs_path) for every engine folder in the bundled
    `data/titantts engines/` dir and the per-user overlay under
    `%APPDATA%/titosoft/Titan/data/titantts engines/`. User entries override
    bundled entries with the same folder name."""
    try:
        from src.platform_utils import discover_data_entries
        entries = discover_data_entries('titantts engines')
        for name, path in entries.items():
            yield name, path
        return
    except Exception as e:
        _log(f"[_iter_engine_folders] discover_data_entries failed: {e}")

    # Fallback to bundled-only enumeration
    engines_dir = _get_engines_dir()
    if not os.path.isdir(engines_dir):
        return
    for name in sorted(os.listdir(engines_dir)):
        yield name, os.path.join(engines_dir, name)


class EngineRegistry:
    """
    Discovers, loads, and provides access to all TitanTTS engines.

    Scans data/titantts engines/ for folders with __engine__.TCE config files,
    similar to how ComponentManager scans data/components/.

    Usage:
        registry = get_engine_registry()
        engines = registry.get_available_engines()
        engine = registry.get_engine('elevenlabs')
    """

    def __init__(self):
        self._engines = {}  # engine_id -> TitanTTSEngine instance
        self._platform_proxies = {}  # engine_id -> PlatformEngineProxy
        self._load_engines()

    # ------------------------------------------------------------------
    # Engine loading from data/titantts engines/
    # ------------------------------------------------------------------

    def _load_engines(self):
        """Scan data/titantts engines/ for folders with __engine__.TCE across
        bundled + user overlay. User entries win on folder-name collision."""
        _log(f"[_load_engines] Starting engine scan...")

        discovered = list(_iter_engine_folders())
        _log(f"[_load_engines] Found folders: {[n for n, _ in discovered]}")
        if not discovered:
            print(f"[EngineRegistry] No engines found in bundled or user dir")
            return

        for folder, folder_path in discovered:
            if not os.path.isdir(folder_path):
                continue

            tce_config = os.path.join(folder_path, '__engine__.TCE')
            engine_py = os.path.join(folder_path, '__engine__.py')

            # Skip folders without __engine__.TCE (e.g. espeak/ which is just bundled binaries)
            if not os.path.exists(tce_config):
                _log(f"[_load_engines] {folder}: no __engine__.TCE, skipping")
                continue

            # Skip folders without __engine__.py
            if not os.path.exists(engine_py):
                _log(f"[_load_engines] {folder}: no __engine__.py, skipping")
                print(f"[EngineRegistry] '{folder}' has __engine__.TCE but no __engine__.py, skipping")
                continue

            # Read TCE config
            config = self._read_tce_config(tce_config)
            if config is None:
                continue

            engine_name = config.get('name', folder)
            status = config.get('status', '0')

            # status=0 means enabled, status=1 means disabled (same as components)
            if status == '1':
                print(f"[EngineRegistry] Engine '{engine_name}' ({folder}) is disabled, skipping")
                continue

            _log(f"[_load_engines] {folder}: loading engine '{engine_name}'...")
            self._load_engine(folder, engine_py, folder_path, engine_name)

    def _read_tce_config(self, tce_path):
        """Read __engine__.TCE config file, return dict of [engine] section or None."""
        try:
            parser = configparser.ConfigParser()
            parser.read(tce_path, encoding='utf-8')
            if parser.has_section('engine'):
                return dict(parser.items('engine'))
            else:
                print(f"[EngineRegistry] No [engine] section in {tce_path}")
                return None
        except Exception as e:
            print(f"[EngineRegistry] Error reading {tce_path}: {e}")
            return None

    def _load_engine(self, folder_name, engine_py_path, folder_path, engine_name):
        """Load a single engine from __engine__.py."""
        try:
            _log(f"[_load_engine] {folder_name}: engine_py = {engine_py_path}, exists = {os.path.isfile(engine_py_path)}")

            # Add engine's directory and library paths to sys.path
            if folder_path not in sys.path:
                sys.path.insert(0, folder_path)

            # Read libs from __engine__.TCE config (libs = lib, vendor)
            # Default: lib/ if exists
            _tce_path = os.path.join(folder_path, '__engine__.TCE')
            _lib_dirs = ["lib"]
            if os.path.isfile(_tce_path):
                _cfg = configparser.ConfigParser()
                try:
                    _cfg.read(_tce_path, encoding='utf-8')
                    _libs_str = _cfg.get('engine', 'libs', fallback='')
                    if _libs_str.strip():
                        _lib_dirs = [d.strip() for d in _libs_str.split(',') if d.strip()]
                except Exception:
                    pass
            for _ld in _lib_dirs:
                _full_lib = os.path.join(folder_path, _ld)
                if os.path.isdir(_full_lib) and _full_lib not in sys.path:
                    sys.path.insert(0, _full_lib)

            module_name = f"titantts_engine_{folder_name}"
            spec = _importlib_util.spec_from_file_location(module_name, engine_py_path)
            module = _importlib_util.module_from_spec(spec)

            # Inject translation function from engine's languages/ dir
            languages_dir = os.path.join(folder_path, 'languages')
            if os.path.isdir(languages_dir):
                try:
                    import gettext
                    from src.settings.settings import get_setting
                    lang = get_setting('language', 'pl')
                    trans = gettext.translation('engine', languages_dir, languages=[lang], fallback=True)
                    module._ = trans.gettext
                except Exception:
                    module._ = lambda s: s
            else:
                module._ = lambda s: s

            _log(f"[_load_engine] {folder_name}: executing module...")
            spec.loader.exec_module(module)
            _log(f"[_load_engine] {folder_name}: module executed OK")

            # Engine must define get_engine() returning a TitanTTSEngine instance
            get_engine_func = getattr(module, 'get_engine', None)
            if get_engine_func is None:
                _log(f"[_load_engine] {folder_name}: no get_engine() function!")
                print(f"[EngineRegistry] Engine '{folder_name}' has no get_engine() function")
                return

            engine = get_engine_func()
            _log(f"[_load_engine] {folder_name}: engine_id={engine.engine_id}, available={engine.is_available()}")

            if engine.engine_id in self._engines:
                _log(f"[_load_engine] {folder_name}: CONFLICT with existing engine_id '{engine.engine_id}'")
                print(f"[EngineRegistry] Engine '{folder_name}' engine_id '{engine.engine_id}' conflicts with existing engine, skipping")
                return

            self._engines[engine.engine_id] = engine
            _log(f"[_load_engine] {folder_name}: SUCCESS - registered as '{engine.engine_id}'")
            print(f"[EngineRegistry] Loaded engine: {engine.engine_name} ({engine.engine_id}) from {folder_name}/")

        except Exception as e:
            _log(f"[_load_engine] {folder_name}: EXCEPTION: {e}")
            print(f"[EngineRegistry] Error loading engine '{folder_name}': {e}")
            import traceback
            traceback.print_exc()
            _log(f"[_load_engine] {folder_name}: traceback: {traceback.format_exc()}")

    # ------------------------------------------------------------------
    # Platform engine proxies
    # ------------------------------------------------------------------

    def register_platform_engine(self, engine_id, engine_name, available=False):
        """
        Register a platform engine proxy.

        Called by StereoSpeech during initialization to register
        platform engines that it manages internally.
        """
        proxy = PlatformEngineProxy(engine_id, engine_name, available)
        self._platform_proxies[engine_id] = proxy

    def update_platform_availability(self, engine_id, available):
        """Update availability of a platform engine."""
        if engine_id in self._platform_proxies:
            self._platform_proxies[engine_id]._available = available

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_engine(self, engine_id):
        """
        Get engine instance by ID.

        Returns TitanTTSEngine instance or PlatformEngineProxy, or None.
        """
        if engine_id in self._engines:
            return self._engines[engine_id]
        return self._platform_proxies.get(engine_id)

    def get_titantts_engine(self, engine_id):
        """
        Get a TitanTTS-category engine by ID (not platform proxies).

        Returns TitanTTSEngine instance or None.
        """
        return self._engines.get(engine_id)

    def is_titantts_engine(self, engine_id):
        """Check if an engine ID belongs to a TitanTTS engine (not platform)."""
        return engine_id in self._engines

    def get_available_engines(self):
        """
        Return list of all available engines, TitanTTS engines first, then platform.

        Returns:
            list of TitanTTSEngine / PlatformEngineProxy instances
        """
        titantts = [e for e in self._engines.values()
                    if e.is_available()]
        platform = [e for e in self._platform_proxies.values()
                    if e.is_available()]
        return titantts + platform

    def get_all_engines(self):
        """
        Return list of all engines (even unavailable), TitanTTS first, then platform.

        Returns:
            list of TitanTTSEngine / PlatformEngineProxy instances
        """
        titantts = list(self._engines.values())
        platform = list(self._platform_proxies.values())
        return titantts + platform

    def get_config_fields(self, engine_id):
        """
        Get config field descriptors for an engine.

        Returns:
            list of field descriptor dicts, or empty list
        """
        engine = self.get_engine(engine_id)
        if engine and hasattr(engine, 'get_config_fields'):
            return engine.get_config_fields()
        return []


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_registry = None
_registry_lock = threading.Lock()


def get_engine_registry():
    """Return (or create) the global EngineRegistry singleton."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = EngineRegistry()
    return _registry
