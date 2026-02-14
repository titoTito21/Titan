"""Titan IM external module manager.

Loads communicator modules from data/titanIM_modules/ directory.
Each module has __im.TCE config and init.py with open(parent_frame) function.
Automatically injects unified TitanIM Sound API and local translations
into every loaded module.
"""
import os
import sys
import gettext as _gettext
import configparser
import importlib.util

from src.network.titanim_sound_api import TitanIMSoundAPI

# Shared sound API instance for all modules
_sound_api = TitanIMSoundAPI()


class TitanIMModuleManager:
    def __init__(self):
        self.modules = []  # list of dicts: {name, id, module, path}

    def load_modules(self):
        """Scan data/titanIM_modules/ and load all valid modules."""
        self.modules = []
        base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "data", "titanIM_modules")

        if not os.path.isdir(base_dir):
            return

        for entry in sorted(os.listdir(base_dir)):
            module_path = os.path.join(base_dir, entry)
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

                spec = importlib.util.spec_from_file_location(
                    f"titanIM_modules.{module_id}", init_file)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mod

                # Inject unified Sound API before executing module code
                # so module can use sounds at import time if needed
                mod.sounds = _sound_api

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

    def open_module(self, name_or_id, parent_frame):
        """Open module by name or id. Returns True if found and opened."""
        for info in self.modules:
            if info["id"] == name_or_id or info["name"] == name_or_id:
                try:
                    info["module"].open(parent_frame)
                    return True
                except Exception as e:
                    print(f"[IM Modules] Error opening {info['name']}: {e}")
                    return False
        return False

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
