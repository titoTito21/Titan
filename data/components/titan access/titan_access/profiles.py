# -*- coding: utf-8 -*-
"""A program's own settings, laid over the reader's.

A setting is a different answer in different programs: the punctuation
level in a terminal and in a mail client, whether the mouse is followed
in a game and in a browser, the voice a document is read in. A profile
is the set of a program's overrides - ``{"Section/Key": value}`` in
``.../titosoft/Titan/accessibility/profiles/<program>.json`` - and
`activate` lays the program in front's overrides over the store
(`settings_store.set_overlay`), so every reader of a setting gets that
program's answer without knowing a profile exists.

The program is named the way the shared per-program answers name it
(`perProgram.application_of`: the executable, or the AT-SPI
application), so a profile made here is keyed the way a reader module is.
`General/Enabled` is never in a profile: whether the reader runs is not a
question a program may answer.
"""

import json
import os
import re
import threading

from titan_access import settings_store

_LOCK = threading.RLock()
_state = {'active': '', 'by_pid': {}}
_cache = {}
_counted = {'activated': 0, 'followed': 0}


def report():
    with _LOCK:
        found = dict(_counted)
        found['active'] = _state['active']
        return found


def forget():
    with _LOCK:
        _cache.clear()
        _state['active'] = ''
        _state['by_pid'].clear()
        for key in _counted:
            _counted[key] = 0
    settings_store.set_overlay({})


# --------------------------------------------------------------------------- #
# Where
# --------------------------------------------------------------------------- #
def folder():
    try:
        from titan_access.portable import readerHome
        where = os.path.join(readerHome.folder(), 'profiles')
    except Exception:                                # noqa: BLE001
        where = os.path.join(settings_store.config_dir(), 'profiles')
    try:
        os.makedirs(where, exist_ok=True)
    except OSError:
        pass
    return where


def _safe(program):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', str(program or '')).strip('_')


def _path(program):
    name = _safe(program)
    return os.path.join(folder(), name + '.json') if name else ''


def _never(section, key):
    try:
        from titan_access import settings_schema
        return (section, key) in settings_schema.NEVER_IN_A_PROFILE
    except Exception:                                # noqa: BLE001
        return (section, key) == ('General', 'Enabled')


# --------------------------------------------------------------------------- #
# Reading and writing one
# --------------------------------------------------------------------------- #
def _load(program):
    with _LOCK:
        if program in _cache:
            return dict(_cache[program])
    data = {}
    path = _path(program)
    if path and os.path.isfile(path):
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                raw = json.load(handle)
            data = {str(k): str(v) for k, v in
                    (raw.get('overrides') or {}).items()}
        except Exception as error:                   # noqa: BLE001
            print('[TitanAccess] profile %s: %s' % (program, error))
    with _LOCK:
        _cache[program] = dict(data)
    return data


def _save(program, data):
    path = _path(program)
    if not path:
        return False
    with _LOCK:
        _cache[program] = dict(data)
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump({'program': program, 'overrides': data}, handle,
                      ensure_ascii=False, indent=1, sort_keys=True)
        return True
    except Exception as error:                       # noqa: BLE001
        print('[TitanAccess] profile %s: %s' % (program, error))
        return False


def programs():
    """Every program that has a profile, by name, sorted."""
    found = []
    try:
        for name in os.listdir(folder()):
            if name.endswith('.json'):
                try:
                    with open(os.path.join(folder(), name), 'r',
                              encoding='utf-8') as handle:
                        found.append(str(json.load(handle).get('program')
                                         or name[:-5]))
                except Exception:                    # noqa: BLE001
                    found.append(name[:-5])
    except OSError:
        pass
    return sorted(set(found))


def overrides(program):
    """``{(section, key): value}`` of a program's profile."""
    out = {}
    for name, value in _load(program).items():
        if '/' in name:
            section, key = name.split('/', 1)
            if not _never(section, key):
                out[(section, key)] = value
    return out


def get(program, section, key):
    """What a profile says about one setting, or None."""
    if not program:
        return None
    return _load(program).get('%s/%s' % (section, key))


def override(program, section, key, value):
    if not program or _never(section, key):
        return False
    data = _load(program)
    data['%s/%s' % (section, key)] = str(value)
    return _save(program, data)


def clear(program, section, key):
    data = _load(program)
    data.pop('%s/%s' % (section, key), None)
    return _save(program, data)


def remove(program):
    with _LOCK:
        _cache.pop(program, None)
    path = _path(program)
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError as error:
        print('[TitanAccess] profile %s: %s' % (program, error))
        return False
    if _state['active'] == program:
        activate('', force=True)
    return True


# --------------------------------------------------------------------------- #
# The program in front
# --------------------------------------------------------------------------- #
def activate(program, force=False):
    """Lay *program*'s overrides over the store. True when that changed
    anything a reader of the settings would see."""
    program = str(program or '')
    with _LOCK:
        if program == _state['active'] and not force:
            return False
        _state['active'] = program
        _counted['activated'] += 1
    settings_store.set_overlay(overrides(program) if program else {})
    return True


def active():
    return _state['active']


def program_of(obj):
    """The program a (shared-shape) object belongs to, '' for none."""
    try:
        from titan_access.portable import perProgram
        return str(perProgram.application_of(obj) or '')
    except Exception:                                # noqa: BLE001
        return ''


def program_in_front():
    try:
        from titan_access.portable import perProgram
        return str(perProgram.application_of() or '')
    except Exception:                                # noqa: BLE001
        return ''


def follow(adapted, engine=None, pid=0):
    """The focus has moved: make the program in front's profile the one in
    force. Cheap on the focus path - the program is remembered per process
    id, so naming it costs one lookup after the first."""
    with _LOCK:
        _counted['followed'] += 1
        known = _state['by_pid'].get(pid) if pid else None
    if known is None:
        known = program_of(adapted)
        if pid:
            with _LOCK:
                if len(_state['by_pid']) > 400:
                    _state['by_pid'].clear()
                _state['by_pid'][pid] = known
    changed = False
    if known != _state['active']:
        # Only a program that HAS a profile changes anything; one that
        # has none puts the global settings back.
        wanted = known if known in programs() else ''
        changed = activate(wanted)
    if changed and engine is not None and hasattr(engine, 'apply_settings'):
        try:
            engine.apply_settings(reason='profile')
        except Exception as error:                   # noqa: BLE001
            print('[TitanAccess] profile apply: %s' % error)
    return changed
