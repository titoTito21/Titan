# -*- coding: utf-8 -*-
"""External application-module loader for Titan Access.

Lets users add (or download) their own per-application modules without editing
the source, mirroring how NVDA discovers ``appModules/<exe>.py``. Any ``*.py``
file dropped into one of the search directories that defines a subclass of
:class:`titan_access.app_modules.base.AppModuleBase` with a non-empty
``process_name`` is loaded and registered for that executable.

Search directories (created lazily, all optional):

* ``<component>/app_modules/extra/`` — modules bundled with or downloaded into
  the component itself.
* ``<settings>/app_modules/`` — a per-user folder inside the Titan screen
  reader's own settings directory (``…/titosoft/Titan/screenreader/app_modules``),
  so downloaded modules live with the reader's settings and survive component
  updates.

An external module may either subclass :class:`AppModuleBase` directly or, for
convenience, name the file ``<exe>.py`` (e.g. ``winword.py``) and expose a class
named ``AppModule``; the loader infers ``process_name`` from the file name when
the class does not set one (NVDA-compatible file naming).

Porting NVDA app modules: NVDA's ``AppModule`` API differs (it overlays
``NVDAObject`` classes and uses ``event_*`` methods tied to NVDA internals), so
NVDA modules do not load verbatim. The Titan API is intentionally close — module
authors override :meth:`AppModuleBase.customize_object` / ``event_*`` /
``get_gestures`` — so porting an NVDA module is mechanical rather than automatic.
"""

import importlib.util
import inspect
import os
import sys

from titan_access.app_modules.base import AppModuleBase


def user_modules_dir():
    """The per-user modules folder inside the screen reader's settings directory
    (``…/titosoft/Titan/screenreader/app_modules``)."""
    try:
        from titan_access.settings_store import config_dir
        return os.path.join(config_dir(), "app_modules")
    except Exception:
        return None


def search_dirs():
    """Return the directories scanned for external modules (in load order)."""
    dirs = [os.path.join(os.path.dirname(__file__), "extra")]
    user_dir = user_modules_dir()
    if user_dir:
        dirs.append(user_dir)
    return dirs


def _iter_module_files():
    for d in search_dirs():
        try:
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".py") and not fn.startswith("_"):
                    yield d, fn
        except Exception as e:
            print(f"[TitanAccess] app module loader: scan error in {d}: {e}")


def _load_file(path, exe_hint):
    """Import a single .py file in isolation; return its module object or None."""
    name = "titan_access_extra_appmod_" + os.path.splitext(os.path.basename(path))[0]
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        # Make the directory importable so a module can ship helper files.
        d = os.path.dirname(path)
        added = d not in sys.path
        if added:
            sys.path.insert(0, d)
        try:
            spec.loader.exec_module(mod)
        finally:
            if added:
                try:
                    sys.path.remove(d)
                except ValueError:
                    pass
        return mod
    except Exception as e:
        print(f"[TitanAccess] app module loader: failed to load {path}: {e}")
        return None


def load_external_modules(engine):
    """Discover and instantiate external modules.

    Returns ``{process_name: AppModuleBase instance}``. Later directories /
    files override earlier ones for the same ``process_name`` so a user folder
    can shadow a bundled module.
    """
    found = {}
    for d, fn in _iter_module_files():
        path = os.path.join(d, fn)
        exe_hint = os.path.splitext(fn)[0].lower()
        mod = _load_file(path, exe_hint)
        if mod is None:
            continue
        for _attr, obj in inspect.getmembers(mod, inspect.isclass):
            # Only concrete subclasses defined in THIS module (not the imported
            # base) qualify.
            if (issubclass(obj, AppModuleBase) and obj is not AppModuleBase
                    and obj.__module__ == mod.__name__):
                try:
                    inst = obj(engine)
                except Exception as e:
                    print(f"[TitanAccess] app module loader: init {obj.__name__} "
                          f"failed: {e}")
                    continue
                proc = (inst.process_name or "").lower() or exe_hint
                if not proc:
                    continue
                inst.process_name = proc
                found[proc] = inst
                print(f"[TitanAccess] app module loaded: {proc} ({fn})")
    return found
