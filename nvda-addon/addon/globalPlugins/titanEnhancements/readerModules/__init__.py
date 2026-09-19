# -*- coding: utf-8 -*-
"""The reader modules, and which one a window gets.

One file per application in this package, each with a ``MODULE`` mapping;
plus whatever the user has written in their own NVDA folder, which loads the
same way and is not a lesser kind of module - a user's own wins over one
shipped here, exactly as Titan's `data/` overlay lets a user's copy of an
add-on win over the bundled one.

**Nothing is imported per focus event.** The package is read once and the
answer for a process is remembered, because the question "which module is
this window's" is asked on the path that reads the screen and everything on
that path is measured in microseconds or it is a reader that hesitates.
"""

import json
import os
import pkgutil
import threading

from . import schema

#: Where a user's own modules live. NVDA's own configuration folder, so
#: they survive an add-on update and are backed up with everything else the
#: user has set.
#: ``.../accessibility/window_data`` - what is known about a program's
#: windows, one folder per program (the executable the module matches),
#: one file per module inside it. A flat file left over from the old
#: ``titanReaderModules`` folder is moved into its program's folder the
#: first time it is read.
FOLDER = 'window_data'

_LOCK = threading.RLock()
_modules = None
_by_pid = {}
_problems = []


def user_folder():
    """The user's own module folder, made on demand - in the folder both
    readers share (`readerHome`), so a module written in one reader is a
    module in the other. '' only when there is nowhere to write."""
    try:
        from .. import readerHome
        path = os.path.join(readerHome.folder(), FOLDER)
    except Exception:                                # noqa: BLE001
        return ''
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return ''
    return path


def _builtin():
    """Every ``MODULE`` in this package, in name order."""
    found = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith('_') or info.name == 'schema':
            continue
        try:
            loaded = __import__('%s.%s' % (__name__, info.name),
                                fromlist=['MODULE'])
        except Exception as error:                   # noqa: BLE001
            _problems.append('%s: %s' % (info.name, error))
            continue
        for data in ([getattr(loaded, 'MODULE', None)]
                     + list(getattr(loaded, 'MODULES', []) or [])):
            if isinstance(data, dict):
                found.append(schema.Module(data, source='built-in'))
    return found


def _from_disk():
    """The user's own, each one checked before it is believed.

    A module that will not parse, or that names rules nothing reads, is
    REPORTED and left out. Loading it anyway is the failure this whole
    format exists to avoid: a module that is nearly right is a control
    that has quietly gone silent.
    """
    folder = user_folder()
    if not folder:
        return []
    found = []
    for path in user_files(folder):
        name = os.path.relpath(path, folder)
        try:
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
        except Exception as error:                   # noqa: BLE001
            _problems.append('%s: %s' % (name, error))
            continue
        wrong = schema.problems(data)
        if wrong:
            _problems.append('%s: %s' % (name, '; '.join(wrong)))
            continue
        path = _tidy(folder, path, data)
        found.append(schema.Module(data, source=path))
    return found


def user_files(folder):
    """Every module file the user has: ``<program>/<module>.json``, and any
    flat ``<module>.json`` left from before there were program folders."""
    out = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for name in names:
        one = os.path.join(folder, name)
        if os.path.isdir(one):
            try:
                inner = sorted(os.listdir(one))
            except OSError:
                continue
            out.extend(os.path.join(one, item) for item in inner
                       if item.lower().endswith('.json'))
        elif name.lower().endswith('.json'):
            out.append(one)
    return out


def program_of(module):
    """The folder a module belongs in: the program it matches, by the
    executable, then by its id. A name that could not be a folder is
    made one."""
    match = module.get('match') if isinstance(module, dict) else None
    name = ''
    if isinstance(match, dict):
        name = str(match.get('executable') or match.get('titan') or '')
    if not name and isinstance(module, dict):
        name = str(module.get('id') or '')
    name = name.strip().lower()
    for bad in '\\/:*?"<>|':
        name = name.replace(bad, '_')
    return name.strip('. ') or 'unknown'


def program_folder(module):
    """``.../window_data/<program>``, made on demand. '' with nowhere."""
    folder = user_folder()
    if not folder:
        return ''
    where = os.path.join(folder, program_of(module))
    try:
        os.makedirs(where, exist_ok=True)
    except OSError:
        return ''
    return where


def _tidy(folder, path, data):
    """A flat module file is moved into its program's folder. The path it
    ends up at is answered; a move that fails leaves it where it was."""
    if os.path.dirname(os.path.abspath(path)) != os.path.abspath(folder):
        return path
    where = program_folder(data)
    if not where:
        return path
    target = os.path.join(where, os.path.basename(path))
    if os.path.exists(target):
        return path
    try:
        os.replace(path, target)
    except OSError:
        return path
    return target


def load(force=False):
    """Every module there is. The user's own last, so theirs wins."""
    global _modules
    with _LOCK:
        if _modules is not None and not force:
            return list(_modules)
        _problems[:] = []
        _modules = _builtin() + _from_disk()
        _by_pid.clear()
        return list(_modules)


def reload():
    """Read the folder again - after the user has written one."""
    return load(force=True)


def problems():
    load()
    return list(_problems)


def forget():
    global _modules
    with _LOCK:
        _modules = None
        _by_pid.clear()


def for_object(obj, application=None):
    """The module for this window, or None. Cheap enough for the focus path.

    Remembered per PROCESS, because that is what a module is about and
    because it is the only key that stays true while an application is
    running: its windows come and go, its titles change with what it is
    showing, and its process does not.
    """
    if obj is None:
        return None
    try:
        pid = int(getattr(obj, 'processID', 0) or 0)
    except (TypeError, ValueError):
        pid = 0
    known = _by_pid.get(pid) if pid else None
    if known is not None:
        return known or None
    for module in load():
        try:
            if module.owns(obj, application):
                if pid:
                    _by_pid[pid] = module
                return module
        except Exception:                            # noqa: BLE001
            continue
    if pid:
        # A window with no module is the common case and must cost one
        # dictionary lookup from now on, not a sweep of every module.
        _by_pid[pid] = False
    return None


def forget_process(pid=0):
    """A process has gone, or Titan has said which is which afresh."""
    with _LOCK:
        if pid:
            _by_pid.pop(int(pid), None)
        else:
            _by_pid.clear()


def describe():
    """What is installed, for the status command and the settings page."""
    rows = []
    for module in load():
        rows.append({'id': module.id, 'label': module.label,
                     'source': module.source,
                     'lists': len(module.lists),
                     'regions': len(module.regions),
                     'controls': len(module.controls),
                     'live': len(module.live),
                     'labels': len(module.labels),
                     'surface': module.reads_surface()})
    return rows
