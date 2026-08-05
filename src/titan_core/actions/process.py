"""Reaching an add-on that runs in its own process (applications and games).

Two ways in, and the manifest's ``mode`` decides which:

- ``live`` - the action needs the running instance ("save the document I have
  open", "what is playing"). It goes over the Action Bus. If the add-on is not
  running and the manifest allows it, Titan starts it and waits for it to join.
- ``headless`` - the action stands on its own ("create a reminder", "search the
  library"). Titan runs the add-on's action module in a short-lived subprocess
  that prints one JSON object, which is faster and does not disturb the user's
  desktop.
- ``any`` (the default) - live when the add-on is already running, headless
  otherwise. This is what most actions want: it uses the open instance when
  there is one and never opens a window just to answer a question.
"""

import json
import os
import subprocess
import sys
import time

from src.titan_core.actions import bus

_HEADLESS_TIMEOUT = 45
_JOIN_TIMEOUT = 20.0


def is_running(addon):
    return bus.get_peer(addon.addon_id) is not None


# --------------------------------------------------------------------------- #
# Headless: one action, one short-lived process
# --------------------------------------------------------------------------- #
def _python_executable():
    try:
        from src.titan_core.app_manager import get_python_executable
        executable, error = get_python_executable()
        if executable:
            return executable, ''
        return '', error or 'no Python interpreter'
    except Exception as e:
        return sys.executable, f'{e}'


def titan_root():
    """Titan's own directory, worked out from this file rather than guessed.

    A packaged ``.TCA``/``.TCD`` add-on runs from the extraction cache, so the
    ``../../..`` an add-on would compute from its own location points nowhere
    near Titan. This has to be right or a packaged add-on's handlers cannot
    import ``src`` at all.
    """
    here = os.path.dirname(os.path.abspath(__file__))       # src/titan_core/actions
    root = os.path.abspath(os.path.join(here, '..', '..', '..'))
    if os.path.isdir(os.path.join(root, 'src')):
        return root
    try:
        from src import platform_utils
        return platform_utils.get_base_path()
    except Exception:
        return root


def _subprocess_env(addon):
    env = os.environ.copy()
    root = titan_root()
    try:
        from src.titan_core.app_manager import SITEPACKAGES_DIR
    except Exception:
        SITEPACKAGES_DIR = ''
    parts = [addon.path, root, SITEPACKAGES_DIR, env.get('PYTHONPATH', '')]
    lib = os.path.join(addon.path, 'lib')
    if os.path.isdir(lib):
        parts.insert(0, lib)
    env['PYTHONPATH'] = os.pathsep.join(p for p in parts if p)
    env['TITAN_ACTION_HEADLESS'] = '1'
    # Handlers should read this instead of computing '../../..' from their own
    # file, which is wrong for a packaged add-on.
    env['TITAN_ROOT'] = root
    return env


def _last_json_object(text):
    """Handlers and their imports print things. The result is the last complete
    JSON object on stdout, so a stray print never breaks an action."""
    for line in reversed((text or '').splitlines()):
        line = line.strip()
        if not (line.startswith('{') and line.endswith('}')):
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict) and 'ok' in parsed:
            return parsed
    return None


def call_headless(addon, action, args, timeout=None):
    timeout = timeout or getattr(action, 'timeout', 0) or _HEADLESS_TIMEOUT
    entry = addon.entry_path()
    if not entry:
        return False, (f"'{addon.label}' has no action module, so "
                       f"'{action.name}' can only run while it is open.")
    executable, error = _python_executable()
    if not executable:
        return False, f"Cannot run {addon.label}'s actions: {error}"

    command = [executable, entry, action.name,
               json.dumps(args or {}, ensure_ascii=False)]
    kwargs = {}
    if sys.platform == 'win32':
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE
        kwargs['startupinfo'] = info
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            command, cwd=addon.path, env=_subprocess_env(addon),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired:
        return False, (f"'{action.qualified}' did not finish within "
                       f"{timeout} seconds.")
    except Exception as e:
        return False, f"Could not run '{action.qualified}': {e}"

    stdout = completed.stdout.decode('utf-8', errors='replace')
    payload = _last_json_object(stdout)
    if payload is None:
        stderr = completed.stderr.decode('utf-8', errors='replace').strip()
        detail = stderr.splitlines()[-1] if stderr else (stdout.strip()[-300:] or
                                                         'no output')
        return False, f"'{action.qualified}' returned nothing usable: {detail}"
    if not payload.get('ok'):
        return False, str(payload.get('error') or 'the action failed')
    result = payload.get('result')
    if result is None:
        return True, f"Done ({action.qualified})."
    # A question or a stated failure travels as a marked dict and must reach
    # the dispatcher intact rather than being flattened into prose.
    if isinstance(result, dict) and (result.get('__titan_question__')
                                     or result.get('__titan_failed__')):
        return False, result
    if not isinstance(result, str):
        try:
            result = json.dumps(result, ensure_ascii=False)
        except Exception:
            result = str(result)
    return True, result


# --------------------------------------------------------------------------- #
# Live: the running instance, over the bus
# --------------------------------------------------------------------------- #
def _launch(addon):
    """Start the add-on so it can join the bus. Returns (ok, error)."""
    try:
        if addon.kind == 'game':
            from src.titan_core import game_manager
            games = {g.get('name'): g for g in game_manager.get_games()}
            info = games.get(addon.label) or games.get(addon.name)
            if info is None:
                return False, f"'{addon.label}' could not be found among the games"
            game_manager.open_game(info)
            return True, ''
        from src.titan_core import app_manager
        info = app_manager.read_app_info(addon.path)
        if not info:
            return False, f"'{addon.label}' has no application manifest"
        app_manager.open_application(info)
        return True, ''
    except Exception as e:
        return False, f"could not start {addon.label}: {e}"


def wait_for_join(addon_id, timeout=_JOIN_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if bus.get_peer(addon_id) is not None:
            return True
        time.sleep(0.25)
    return False


def call_live(addon, action, args, allow_launch=True):
    peer = bus.get_peer(addon.addon_id)
    if peer is None:
        # The action decides, falling back to the add-on. Starting an editor to
        # answer "what have you got open" is not a helpful reading of
        # launch_if_needed.
        wanted = getattr(action, 'launch', None)
        if wanted is None:
            wanted = addon.launch_if_needed
        if not (allow_launch and wanted):
            return False, (f"'{addon.label}' is not running, and "
                           f"'{action.name}' needs it to be open.")
        started, error = _launch(addon)
        if not started:
            return False, error
        if not wait_for_join(addon.addon_id):
            return False, (f"Started '{addon.label}', but it did not connect to "
                           f"Titan, so '{action.name}' could not be delivered. "
                           f"It may be an older version that does not support "
                           f"being controlled.")
    return bus.invoke(addon.addon_id, action.name, args)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def call(addon, action, args):
    """Run an out-of-process action. Returns (ok, text)."""
    if action.mode == 'headless':
        return call_headless(addon, action, args)
    if action.mode == 'live':
        return call_live(addon, action, args)
    # 'any': use the open instance when there is one, otherwise stay out of the
    # user's way and answer from a short-lived process.
    if is_running(addon):
        ok, result = call_live(addon, action, args, allow_launch=False)
        if ok:
            return True, result
        if addon.entry_path():
            return call_headless(addon, action, args)
        return False, result
    if addon.entry_path():
        return call_headless(addon, action, args)
    return call_live(addon, action, args)
