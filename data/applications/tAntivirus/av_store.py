# -*- coding: utf-8 -*-
"""Where Titan Antivirus keeps what it knows, and what the user has chosen.

Everything lives under Titan's own user folder -
``%APPDATA%/titosoft/Titan/antivirus`` (``~/.config/titosoft/Titan/antivirus``
elsewhere) - and nothing is written beside the application, because a
compiled Titan's ``data/`` folder may not be writable and an update replaces
it whole:

    engine/        the ClamAV that was downloaded for this machine
    db/            its signature databases (freshclam writes them)
    quarantine/    files taken out of the way, made unrunnable
    requests/      what the shell add-on asked for, one JSON file per ask
    settings.json  the user's choices
    history.json   what every scan found

This module imports neither wx nor anything of Titan's, so the shell add-on
- which runs inside Titan's own process - can use it to hand a scan over.
"""

import json
import os
import sys
import threading
import time
import uuid

_LOCK = threading.RLock()

#: What a fresh installation answers. A key a later version adds is read
#: from here until the user changes it, so an old settings file never has
#: to be migrated.
DEFAULTS = {
    # 'ask' | 'quarantine' | 'delete' | 'report'
    'threat_action': 'ask',
    # Minutes of nothing to scan before clamd is stopped; 0 keeps it up.
    'clamd_idle_minutes': 10,
    'use_clamd': True,
    'clamd_port': 33310,
    'exclusions': [],
    'max_file_mb': 200,
    'scan_archives': True,
    'watch_downloads': False,
    'schedule_enabled': False,
    'schedule_time': '12:00',
    # 'quick' | 'full' | 'custom'
    'schedule_scope': 'quick',
    'schedule_folders': [],
    'schedule_last_day': '',
    'update_on_start': True,
    'last_update': 0,
}

HISTORY_LIMIT = 200


def base_folder():
    """The folder everything is kept in, made on demand."""
    if sys.platform == 'win32':
        root = os.path.join(os.environ.get('APPDATA')
                            or os.path.expanduser('~'), 'titosoft', 'Titan')
    elif sys.platform == 'darwin':
        root = os.path.expanduser(
            '~/Library/Application Support/titosoft/Titan')
    else:
        root = os.path.expanduser('~/.config/titosoft/Titan')
    folder = os.path.join(root, 'antivirus')
    os.makedirs(folder, exist_ok=True)
    return folder


def folder(name):
    path = os.path.join(base_folder(), name)
    os.makedirs(path, exist_ok=True)
    return path


def _read_json(path, fallback):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return fallback


def _write_json(path, value):
    """Written to a side file and moved into place, so a crash halfway
    through leaves the old file rather than half of a new one."""
    temporary = path + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=1)
    os.replace(temporary, path)


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def settings():
    with _LOCK:
        stored = _read_json(os.path.join(base_folder(), 'settings.json'), {})
        merged = dict(DEFAULTS)
        if isinstance(stored, dict):
            merged.update({key: value for key, value in stored.items()
                           if key in DEFAULTS})
        return merged


def get(key):
    return settings().get(key, DEFAULTS.get(key))


def update(**changes):
    with _LOCK:
        current = settings()
        current.update({key: value for key, value in changes.items()
                        if key in DEFAULTS})
        _write_json(os.path.join(base_folder(), 'settings.json'), current)
        return current


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------
def history():
    with _LOCK:
        value = _read_json(os.path.join(base_folder(), 'history.json'), [])
        return value if isinstance(value, list) else []


def add_history(record):
    """One finished scan: when, what, by which engine, and what it found."""
    with _LOCK:
        records = history()
        records.insert(0, record)
        del records[HISTORY_LIMIT:]
        _write_json(os.path.join(base_folder(), 'history.json'), records)


# --------------------------------------------------------------------------
# Requests: the shell add-on asking the application for a scan
# --------------------------------------------------------------------------
def write_request(paths, engine='clamav', kind='scan'):
    """Park a request where the application looks for one; answer its path.

    A file rather than a socket because the application may not be running
    yet - Titan then starts it with the request's path as its argument, and
    a running one picks the file up from the folder within a second.
    """
    request = {'id': uuid.uuid4().hex, 'kind': kind, 'engine': engine,
               'paths': [str(path) for path in paths if path],
               'time': time.time()}
    path = os.path.join(folder('requests'), request['id'] + '.json')
    _write_json(path, request)
    return path


def read_request(path):
    """The request in ``path``, taken off the disk; None when it is not one."""
    request = _read_json(path, None)
    try:
        os.remove(path)
    except OSError:
        pass
    if not isinstance(request, dict) or not request.get('kind'):
        return None
    request['paths'] = [str(one) for one in request.get('paths') or []
                        if str(one).strip()]
    return request


def pending_requests():
    """Every request waiting, oldest first."""
    try:
        names = sorted(os.listdir(folder('requests')))
    except OSError:
        return []
    paths = [os.path.join(folder('requests'), name) for name in names
             if name.endswith('.json')]
    paths.sort(key=lambda one: os.path.getmtime(one)
               if os.path.exists(one) else 0)
    return paths


# --------------------------------------------------------------------------
# One running instance
# --------------------------------------------------------------------------
def _pid_file():
    return os.path.join(base_folder(), 'instance.pid')


def pid_alive(pid):
    if not pid:
        return False
    if sys.platform == 'win32':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259                           # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def running_instance():
    """The pid of a Titan Antivirus that is running now, or 0.

    Windows reuses a pid the moment a process ends, so the file also carries
    when it was written, and a pid older than the machine's last start is
    not believed.
    """
    data = _read_json(_pid_file(), {})
    if not isinstance(data, dict):
        return 0
    pid = int(data.get('pid') or 0)
    if pid and pid != os.getpid() and pid_alive(pid):
        return pid
    return 0


def claim_instance():
    """Write this process down as THE instance. False if another has it."""
    with _LOCK:
        if running_instance():
            return False
        _write_json(_pid_file(), {'pid': os.getpid(), 'time': time.time()})
        return True


def release_instance():
    with _LOCK:
        data = _read_json(_pid_file(), {})
        if isinstance(data, dict) and data.get('pid') == os.getpid():
            try:
                os.remove(_pid_file())
            except OSError:
                pass
