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
    """Return path to data/titantts engines/ directory."""
    try:
        from src.platform_utils import get_base_path
        base = get_base_path()
    except ImportError:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    return os.path.join(base, 'data', 'titantts engines')


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
        """Scan data/titantts engines/ for folders with __engine__.TCE."""
        engines_dir = _get_engines_dir()
        if not os.path.isdir(engines_dir):
            print(f"[EngineRegistry] Engines directory not found: {engines_dir}")
            return

        for folder in sorted(os.listdir(engines_dir)):
            folder_path = os.path.join(engines_dir, folder)
            if not os.path.isdir(folder_path):
                continue

            tce_config = os.path.join(folder_path, '__engine__.TCE')
            engine_py = os.path.join(folder_path, '__engine__.py')

            # Skip folders without __engine__.TCE (e.g. espeak/ which is just bundled binaries)
            if not os.path.exists(tce_config):
                continue

            # Skip folders without __engine__.py
            if not os.path.exists(engine_py):
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

            spec.loader.exec_module(module)

            # Engine must define get_engine() returning a TitanTTSEngine instance
            get_engine_func = getattr(module, 'get_engine', None)
            if get_engine_func is None:
                print(f"[EngineRegistry] Engine '{folder_name}' has no get_engine() function")
                return

            engine = get_engine_func()

            if engine.engine_id in self._engines:
                print(f"[EngineRegistry] Engine '{folder_name}' engine_id '{engine.engine_id}' conflicts with existing engine, skipping")
                return

            self._engines[engine.engine_id] = engine
            print(f"[EngineRegistry] Loaded engine: {engine.engine_name} ({engine.engine_id}) from {folder_name}/")

        except Exception as e:
            print(f"[EngineRegistry] Error loading engine '{folder_name}': {e}")
            import traceback
            traceback.print_exc()

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
