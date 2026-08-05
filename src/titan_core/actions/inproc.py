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


def loaded_modules_under(path):
    """Every already-imported module whose file lives inside ``path``.

    This is what makes a component's *live* state reachable: Titan imported it
    at startup, so the object holding its windows and caches is already in
    ``sys.modules``.
    """
    root = os.path.normpath(os.path.abspath(path))
    found = []
    for module in list(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if not filename:
            continue
        try:
            candidate = os.path.normpath(os.path.abspath(filename))
            if os.path.commonpath([root, candidate]) == root:
                found.append(module)
        except (ValueError, OSError):
            continue
    return found


def candidate_owners(addon):
    """Objects that might hold this add-on's handlers, best first."""
    owners = []
    entry = import_entry(addon)
    if entry is not None:
        owners.append(entry)
    owners.extend(loaded_modules_under(addon.path))
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
