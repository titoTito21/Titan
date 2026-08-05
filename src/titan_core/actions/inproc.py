"""Reaching an add-on that already runs inside Titan's process.

Components, widgets, statusbar applets, TTS engines, gamepad modes, launchers
and Titan IM modules are loaded Python modules, so an action is a direct call.
Two things still have to be worked out: *which* object owns the handler, and
*which thread* to call it on.

The owner is found in the order that respects what the add-on author wrote:

1. the module named by ``entry`` in the manifest, imported from inside the
   add-on's own directory;
2. an already-loaded module whose ``__file__`` lives under the add-on's
   directory - this is the normal case for a component, because Titan loaded it
   at startup and its live state (open windows, caches, sessions) is the state
   the AI should be acting on;
3. a module-level ``TITAN_ACTIONS`` list, which lets a component declare
   actions in Python with real callables and no JSON at all.

The thread is always Titan's GUI thread: an action may open a window, and wx is
not thread-safe.
"""

import importlib.util
import os
import sys
import threading

_import_cache = {}        # absolute path -> (mtime, module)
_import_lock = threading.Lock()


def run_on_gui(func, timeout=30):
    """Run ``func`` on the wx main thread and return (result, error).

    Handlers routinely touch windows, so this is not optional. When wx has no
    running application (a headless run, an early startup call) the function is
    simply called here.
    """
    try:
        import wx
    except Exception:
        try:
            return func(), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    try:
        app = wx.GetApp()
    except Exception:
        app = None
    if app is None or wx.IsMainThread():
        try:
            return func(), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    box = {}
    done = threading.Event()

    def call():
        try:
            box['value'] = func()
        except Exception as e:                   # noqa: BLE001 - relayed below
            box['error'] = f"{type(e).__name__}: {e}"
        finally:
            done.set()

    wx.CallAfter(call)
    if not done.wait(timeout):
        return None, f"the add-on did not respond within {timeout} seconds"
    if 'error' in box:
        return None, box['error']
    return box.get('value'), None


def import_entry(addon):
    """Import the module named by the manifest's ``entry``. Cached on mtime so
    an author can edit a handler and re-run without restarting Titan."""
    path = addon.entry_path()
    if not path:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    with _import_lock:
        cached = _import_cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
    module_name = f"titan_actions_{addon.kind}_{addon.addon_id}"
    try:
        # The add-on's own directory goes first: handlers import their app's
        # modules by their plain names, exactly as the app itself does.
        if addon.path not in sys.path:
            sys.path.insert(0, addon.path)
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        print(f"[actions] Could not load {addon.addon_id}'s handlers: {e}")
        return None
    with _import_lock:
        _import_cache[path] = (mtime, module)
    return module


def _comparable(path):
    """A path in the form two paths may be compared in.

    Windows paths differ in case and in separator between the string a manager
    stored and the string discovery produced (``%APPDATA%`` versus a bundled
    root, a short name, a ``.pyc`` beside its ``.py``), and a case-sensitive
    comparison quietly decides an add-on's module is not its own - which is
    exactly how a component's actions become invisible.
    """
    text = os.path.normpath(os.path.abspath(path))
    return os.path.normcase(text)


def loaded_modules_under(path):
    """Every already-imported module whose file lives inside ``path``.

    This is what makes a component's *live* state reachable: Titan imported it
    at startup, so the object holding its windows and caches is already in
    ``sys.modules``.
    """
    root = _comparable(path)
    found = []
    for module in list(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if not filename:
            continue
        try:
            candidate = _comparable(filename)
            if candidate == root or candidate.startswith(root + os.sep):
                found.append(module)
        except (ValueError, OSError):
            continue
    return found


def modules_named_after(addon):
    """Modules registered in ``sys.modules`` under the add-on's own name.

    Every in-process manager imports an add-on under its folder name
    (``sys.modules['zegarynka']``), and some of them build the module by hand
    with ``types.ModuleType`` - which leaves ``__file__`` pointing at whatever
    string the manager happened to hold, or at nothing at all. Looking the name
    up directly finds those, so an add-on's actions do not depend on two
    unrelated pieces of code having spelt the same path the same way.
    """
    folder = os.path.basename(os.path.normpath(addon.path))
    found = []
    for name in (addon.name, folder, addon.addon_id):
        if not name:
            continue
        module = sys.modules.get(name)
        if module is None or module in found:
            continue
        # A name alone is not proof: some other module may simply be called
        # 'macros'. Accept it when it carries no file at all (a module built by
        # hand, which is what the frozen loader does) or when it does sit in a
        # directory of this add-on's name - a second copy of the same add-on
        # under the other root.
        filename = getattr(module, '__file__', None)
        if filename:
            try:
                owner = os.path.basename(os.path.dirname(_comparable(filename)))
            except (ValueError, OSError):
                continue
            if owner != os.path.normcase(folder):
                continue
        found.append(module)
    return found


def candidate_owners(addon):
    """Objects that might hold this add-on's handlers, best first."""
    owners = []
    entry = import_entry(addon)
    if entry is not None:
        owners.append(entry)
    for module in loaded_modules_under(addon.path) + modules_named_after(addon):
        if module not in owners:
            owners.append(module)
    return owners


def resolve_callable(addon, action):
    """Find the function implementing ``action``, or None."""
    if action.run is not None:
        return action.run
    for owner in candidate_owners(addon):
        # A declared TITAN_ACTIONS entry with a real callable wins over a
        # same-named module attribute: it is the author's explicit mapping.
        declared = getattr(owner, 'TITAN_ACTIONS', None)
        if isinstance(declared, (list, tuple)):
            for raw in declared:
                if not isinstance(raw, dict):
                    continue
                if str(raw.get('name', '')).strip().lower() == action.name:
                    handler = raw.get('run') or raw.get('handler')
                    if callable(handler):
                        return handler
                    if isinstance(handler, str):
                        found = getattr(owner, handler, None)
                        if callable(found):
                            return found
        found = getattr(owner, action.handler, None)
        if callable(found):
            return found
    return None


def actions_from_module(module, addon):
    """Parse a module-level ``TITAN_ACTIONS`` declaration.

        TITAN_ACTIONS = [
            {'name': 'say_time', 'summary': 'Speak the current time.',
             'run': say_time},
        ]

    The callable is kept on the ActionSpec, so no name lookup happens later.
    """
    from src.titan_core.actions.manifest import _parse_action     # noqa: PLC0415

    declared = getattr(module, 'TITAN_ACTIONS', None)
    if not isinstance(declared, (list, tuple)):
        return []
    actions = []
    warnings = addon.warnings

    def warn(message):
        if len(warnings) < 12:
            warnings.append(message)

    for raw in declared:
        if not isinstance(raw, dict):
            continue
        action = _parse_action(raw, addon, warn)
        if action is None:
            continue
        handler = raw.get('run')
        if callable(handler):
            action.run = handler
        actions.append(action)
    return actions


def call(addon, action, args):
    """Run an in-process action. Returns (ok, text)."""
    handler = resolve_callable(addon, action)
    if handler is None:
        return False, (f"'{addon.label}' declares the action '{action.name}' "
                       f"but no handler for it could be found. The add-on may "
                       f"not be loaded, or its entry module is missing.")
    value, error = run_on_gui(lambda: handler(**args))
    if error:
        return False, error
    return True, value
