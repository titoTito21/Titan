# -*- coding: utf-8 -*-
"""
Titan alternative updater (TAU).

Titan's own updater runs inside the Titan it is replacing, and a compiled
Titan up to 0.6.1 fails at that (see "The updater" in CLAUDE.md). The way
out is updater.bat, which updates the installation from OUTSIDE Titan - and
which nobody finds by themselves. So this component reads the update log the
built-in updater writes (%APPDATA%/titosoft/Titan/logs/update.log) at every
start, and when the last update either

  * failed ("[UPDATER] update failed: ..."), or
  * was reported as applied, and yet the Titan running now is still not the
    version it was supposed to install,

it asks once whether to use the alternative updater. Yes copies updater.bat
to %TEMP% (the archive it unpacks contains the bat itself, and cmd.exe reads
a batch file as it goes), starts it, and closes Titan; the bat waits for
Titan to go, updates, and starts Titan again.

Every attempt is asked about once: the answer, yes or no, is remembered in
%APPDATA%/titosoft/Titan/tau.ini by the attempt's time in the log.
"""

import os
import re
import sys
import shutil
import subprocess
import tempfile
import threading
import configparser

COMPONENT_DIR = os.path.dirname(os.path.abspath(__file__))
TCE_ROOT = os.path.abspath(os.path.join(COMPONENT_DIR, '..', '..', '..'))
if TCE_ROOT not in sys.path:
    sys.path.insert(0, TCE_ROOT)

try:
    import wx
except ImportError:          # the analysis below still works without wx
    wx = None

try:
    from src.settings.settings import get_setting
except Exception:
    def get_setting(key, default='', section='general'):
        return default

try:
    import gettext
    _translation = gettext.translation(
        'tau', localedir=os.path.join(COMPONENT_DIR, 'languages'),
        languages=[get_setting('language', 'pl')], fallback=True)
    _ = _translation.gettext
except Exception:
    def _(text):
        return text


BAT_NAME = 'updater.bat'
#: How long after startup the question is asked: late enough for Titan's
#: window to be up and its startup speech to be over.
ASK_AFTER_MS = 4000

_LINE = re.compile(r'^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (.*)$')
_OFFERED = re.compile(r'\[UPDATER\] update offered: (\S+) -> (\S+)')


# ---------------------------------------------------------------------------
# What the log says
# ---------------------------------------------------------------------------

def user_dir():
    base = os.getenv('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'titosoft', 'Titan')


def log_paths():
    """update.log and the one it was rotated into, oldest first."""
    path = os.path.join(user_dir(), 'logs', 'update.log')
    return [path + '.1', path]


def read_log():
    text = []
    for path in log_paths():
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                text.append(f.read())
        except OSError:
            pass
    return '\n'.join(text)


def attempts(text):
    """Every update the built-in updater offered, in order, as dicts:
    {'time', 'current', 'target', 'outcome'} where outcome is 'failed',
    'applied', 'declined' or None (the log ends before an answer)."""
    found = []
    last = None
    for raw in text.splitlines():
        match = _LINE.match(raw.strip())
        if not match:
            continue
        stamp, message = match.groups()
        offered = _OFFERED.search(message)
        if offered:
            last = {'time': stamp, 'current': offered.group(1),
                    'target': offered.group(2), 'outcome': None}
            found.append(last)
            continue
        if last is None or last['outcome'] is not None:
            continue
        if '[UPDATER] update failed' in message:
            last['outcome'] = 'failed'
        elif '[UPDATER] update applied successfully' in message:
            last['outcome'] = 'applied'
        elif 'Update declined by user' in message:
            last['outcome'] = 'declined'
    return found


def find_problem(text, running_version, handled_after=''):
    """The newest attempt that went wrong and has not been asked about.

    Wrong is: it failed, or it said it was applied and the version running
    now is not the one it installed. Either way only while the version
    running now is still not that target - an installation brought up to
    date some other way has nothing left to fix. ``handled_after`` is the
    time of the last attempt already asked about (log times sort as text).
    """
    running = str(running_version or '').strip()
    if not running:
        return None
    for attempt in reversed(attempts(text)):
        if attempt['time'] <= handled_after:
            return None
        if attempt['target'] == running or attempt['current'] != running:
            return None          # wanted this version, or made by another
        if attempt['outcome'] in ('failed', 'applied'):
            return attempt
    return None


def running_version():
    main_mod = sys.modules.get('__main__')
    version = getattr(main_mod, 'VERSION', None)
    return str(version).strip() if version else None


# ---------------------------------------------------------------------------
# What has been asked already
# ---------------------------------------------------------------------------

def _state_path():
    return os.path.join(user_dir(), 'tau.ini')


def handled_after():
    config = configparser.ConfigParser()
    try:
        config.read(_state_path(), encoding='utf-8')
        return config.get('tau', 'handled', fallback='')
    except Exception:
        return ''


def remember(attempt_time):
    config = configparser.ConfigParser()
    config['tau'] = {'handled': attempt_time}
    try:
        os.makedirs(user_dir(), exist_ok=True)
        with open(_state_path(), 'w', encoding='utf-8') as f:
            config.write(f)
    except OSError as e:
        print(f"[tau] could not remember the answer: {e}")


# ---------------------------------------------------------------------------
# Running the alternative updater
# ---------------------------------------------------------------------------

def install_dir():
    """Where Titan.exe is - updater.bat refuses any other folder."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return None


def can_run():
    """Why the alternative updater cannot run here, or None when it can."""
    if sys.platform != 'win32':
        return _("The alternative updater works on Windows only.")
    folder = install_dir()
    if not folder or not os.path.exists(os.path.join(folder, 'Titan.exe')):
        return _("The alternative updater updates a compiled Titan only; "
                 "this one runs from source.")
    if not os.path.exists(os.path.join(COMPONENT_DIR, BAT_NAME)):
        return _("updater.bat is missing from the component's folder.")
    return None


def start_updater():
    """Copy updater.bat out of the installation and start it. True if it
    started. It waits for Titan to close, updates it and starts it again."""
    problem = can_run()
    if problem:
        print(f"[tau] {problem}")
        return False
    work = os.path.join(tempfile.gettempdir(), 'titan_tau')
    try:
        os.makedirs(work, exist_ok=True)
        bat = os.path.join(work, BAT_NAME)
        shutil.copy2(os.path.join(COMPONENT_DIR, BAT_NAME), bat)
        subprocess.Popen(
            ['cmd.exe', '/c', bat, install_dir(), '/y', '/wait', '/restart'],
            cwd=work, close_fds=True,
            creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0x10))
        return True
    except Exception as e:
        print(f"[tau] could not start {BAT_NAME}: {e}")
        return False


def close_titan():
    """Close Titan without its exit confirmation - the user has just said
    yes to closing it. Every face of Titan has shutdown_app()."""
    if wx is None or wx.GetApp() is None:
        return
    for window in wx.GetTopLevelWindows():
        if hasattr(window, 'shutdown_app'):
            window.shutdown_app()
            return
    try:
        from src.shell.shutdown_dialog import exit_titan
        if exit_titan():
            return
    except Exception:
        pass
    wx.GetApp().ExitMainLoop()


def run_alternative_updater(parent=None):
    """Start updater.bat and close Titan; says why when it cannot."""
    problem = can_run()
    if problem:
        if wx is not None and wx.GetApp() is not None:
            wx.MessageBox(problem, _("Titan alternative updater"),
                          wx.OK | wx.ICON_ERROR, parent)
        return False
    if not start_updater():
        if wx is not None and wx.GetApp() is not None:
            wx.MessageBox(_("The alternative updater could not be started."),
                          _("Titan alternative updater"),
                          wx.OK | wx.ICON_ERROR, parent)
        return False
    close_titan()
    return True


def _question_sound():
    try:
        from src.titan_core.sound import play_sound
        play_sound('ui/dialog.ogg')
    except Exception:
        pass


def ask(attempt):
    """The question, on the GUI thread."""
    remember(attempt['time'])
    _question_sound()
    parent = wx.GetApp().GetTopWindow() if wx.GetApp() else None
    dialog = wx.MessageDialog(
        parent,
        _("It looks like there was an update error. "
          "Do you want to use the alternative updater?"),
        _("Titan alternative updater"),
        wx.YES_NO | wx.ICON_QUESTION)
    try:
        answer = dialog.ShowModal()
    finally:
        dialog.Destroy()
    if answer == wx.ID_YES:
        run_alternative_updater(parent)


def check(show=True):
    """Look at the log; ask when an attempt went wrong. Returns the attempt."""
    try:
        attempt = find_problem(read_log(), running_version(), handled_after())
    except Exception as e:
        print(f"[tau] could not read the update log: {e}")
        return None
    if attempt and show and can_run() is None and wx is not None \
            and wx.GetApp() is not None:
        wx.CallLater(ASK_AFTER_MS, ask, attempt)
    return attempt


# ---------------------------------------------------------------------------
# Component hooks
# ---------------------------------------------------------------------------

def initialize(app=None):
    if wx is not None and wx.GetApp() is not None:
        wx.CallAfter(check)
    else:
        threading.Thread(target=check, kwargs={'show': False},
                         daemon=True).start()


def shutdown():
    pass


def on_menu_run(event=None):
    run_alternative_updater()


def add_menu(component_manager):
    component_manager.register_menu_function(
        _("Run alternative updater"), on_menu_run)


# ---------------------------------------------------------------------------
# Titan actions
# ---------------------------------------------------------------------------

try:
    from src.titan_core.actions import fails
except Exception:
    def fails(reason):
        return reason


def action_status():
    attempt = find_problem(read_log(), running_version())
    if not attempt:
        return "The last update did not go wrong; nothing to repair."
    what = ("failed" if attempt['outcome'] == 'failed'
            else "was reported as applied but did not change the version")
    return (f"The update from {attempt['current']} to {attempt['target']} "
            f"at {attempt['time']} {what}.")


def action_run():
    problem = can_run()
    if problem:
        return fails(problem)
    if not run_alternative_updater():
        return fails("The alternative updater could not be started.")
    return "The alternative updater was started and Titan is closing."


TITAN_ACTIONS = [
    {'name': 'status',
     'summary': "Say whether Titan's last update failed or did not change "
                "the version.",
     'run': action_status},
    {'name': 'run',
     'summary': "Close Titan and update it with the alternative updater "
                "(updater.bat), which works from outside Titan.",
     'risk': 'confirm', 'run': action_run},
]
