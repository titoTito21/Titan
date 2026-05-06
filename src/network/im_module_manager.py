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
from src.platform_utils import get_base_path

# Shared sound API instance for all modules
_sound_api = TitanIMSoundAPI()

# Lazily created hidden wx host frame used as fallback parent when the
# caller does not supply one. This lets IM modules work from any TCE
# entry point - main GUI, Invisible UI, Klango mode, launcher mode - even
# when no top-level window is currently available.
_fallback_parent = None


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

    def load_modules(self):
        """Scan data/titanIM_modules/ and load all valid modules."""
        self.modules = []
        base_dir = os.path.join(get_base_path(), "data", "titanIM_modules")

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
                    effective_parent = _resolve_parent(parent_frame)
                    info["module"].open(effective_parent)
                    return True
                except Exception as e:
                    print(f"[IM Modules] Error opening {info['name']}: {e}")
                    import traceback
                    traceback.print_exc()
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
