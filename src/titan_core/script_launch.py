"""Running a Titan Script (.TCS) that Titan was asked to open.

Double-clicking a ``.tcs`` in Explorer - or passing one on the command line -
launches Titan with ``--run-script <path>``. The script cannot be run there and
then: it is written in Titan's own actions, so it needs the add-ons loaded and
the action registry built, neither of which has happened when the arguments are
read.

So the path is *parked* here, and ``ComponentManager.initialize_components()``
runs it at the one moment where everything a script can name exists. That also
puts the check in exactly one place for all three startup modes (normal, Klango
and launcher), instead of three copies that would drift.

The language itself lives in the Macro Manager component, because that is where
a script belongs - it is a macro, listed and editable beside the others. If that
component is not installed, a ``.tcs`` cannot run, and saying so plainly is the
whole of this module's error handling.
"""

import os
import sys
import threading

_pending = None
_lock = threading.Lock()

MACROS_COMPONENT = 'macros'


def set_pending(path):
    """Remember a script to run once Titan's add-ons are loaded."""
    global _pending
    if not path:
        return False
    with _lock:
        _pending = str(path)
    return True


def take_pending():
    """The parked script path, once. None when there is none."""
    global _pending
    with _lock:
        path, _pending = _pending, None
    return path


def looks_like_script(path):
    return bool(path) and str(path).strip().lower().endswith('.tcs')


def _macros_component():
    """The loaded Macro Manager component, or None.

    It is looked up by the name ComponentManager registers it under, and then
    checked for the function that actually runs a script - a component of that
    name from somewhere else is not this one.
    """
    module = sys.modules.get(MACROS_COMPONENT)
    if module is not None and hasattr(module, 'run_tcs'):
        return module
    for candidate in list(sys.modules.values()):
        if hasattr(candidate, 'run_tcs') and hasattr(candidate, 'TCS_EXT'):
            return candidate
    return None


def _report(message, level='error'):
    print(f"[TitanScript] {message}")
    try:
        from src.system.notifications import speak_notification
        speak_notification(message, level)
    except Exception:
        pass


def run(path):
    """Run one Titan Script. Returns True when it was handed over to run."""
    script = str(path or '').strip().strip('"')
    if not script:
        return False
    script = os.path.abspath(os.path.expandvars(os.path.expanduser(script)))
    if not os.path.isfile(script):
        _report(f"There is no script at {script}")
        return False

    component = _macros_component()
    if component is None:
        _report("Titan Scripts need the Macro Manager component, which is not "
                "installed or is switched off.")
        return False
    try:
        component.run_tcs(script)
    except Exception as e:                           # noqa: BLE001 - reported
        _report(f"{os.path.basename(script)} could not be run: {e}")
        return False
    print(f"[TitanScript] running {script}")
    return True


def run_pending():
    """Run the parked script, if Titan was asked to open one."""
    path = take_pending()
    if not path:
        return False
    return run(path)
