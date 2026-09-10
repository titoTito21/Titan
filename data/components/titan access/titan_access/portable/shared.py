# -*- coding: utf-8 -*-
"""What the user has taught one reader, known to the other.

Somebody who reads this desktop uses NVDA with this add-on, or Titan
Access, or both - and what they accumulate is the same thing either way: a
control the program never named and they named themselves, a picture they
had read once, a note they wanted said. Keeping two copies of that means
the work is done twice, and a user who switches readers loses the half they
are not in.

**So there is one place, and it is Titan's.**
``%APPDATA%/titosoft/Titan/screenreader/shared/`` - the folder Titan Access
already owns, which exists whether or not NVDA is installed and survives
the add-on being reinstalled. Each reader keeps its own file as well and
neither is authoritative: they are MERGED, so a machine where one of them
has not run for a month does not lose what the other learned.

Three rules decide a conflict, and each of them is a real case:

* **The user's own is never overwritten by a guess.** A name they typed
  beats one an AI read off a picture, whichever is newer. This is the rule
  :mod:`labels` already follows within one reader, and it does not stop
  being right because the guess came from the other one.
* **Otherwise the newest wins**, by the time it was written down.
* **A row that only one side has is kept.** Merging is not choosing.

**It never runs on the focus path.** Reading and writing a JSON file is
milliseconds, and milliseconds on every arrival is a reader that has got
slower for no reason the user can see. It happens when Titan connects,
when the user changes something, and when they ask - and never in an
event handler.
"""

import json
import os
import threading

_LOCK = threading.RLock()

#: What is shared, and the file it lives in. Deliberately a short list:
#: something is here because losing it when you switch readers would be
#: annoying, not because it happens to be stored.
STORES = {
    'labels': 'controlNames.json',
}

_counted = {'merged': 0, 'taken': 0, 'given': 0, 'conflicts': 0}
_last_error = ''


def _text(value):
    return str(value or '').strip()


def folder():
    """Titan's own shared folder for readers. ``''`` when there is none.

    Found the way Titan Access finds its own settings, because it has to
    be the SAME folder - a second guess at where Titan keeps things is a
    second folder, and then nothing is shared at all.
    """
    try:
        import platform
        system = platform.system()
        if system == 'Windows':
            base = os.getenv('APPDATA') or os.path.expanduser('~')
            base = os.path.join(base, 'titosoft', 'Titan')
        elif system == 'Darwin':
            base = os.path.join(os.path.expanduser('~'), 'Library',
                                'Application Support', 'titosoft', 'Titan')
        else:
            base = os.path.join(os.path.expanduser('~'), '.config',
                                'titosoft', 'Titan')
        return os.path.join(base, 'screenreader', 'shared')
    except Exception:                                # noqa: BLE001
        return ''


def path(store):
    """Where one shared store lives, or ``''``."""
    name = STORES.get(_text(store))
    where = folder()
    if not name or not where:
        return ''
    return os.path.join(where, name)


def available():
    """``(yes, why not)`` - whether there is anywhere to share.

    Titan not being installed is a perfectly ordinary answer: this add-on
    works on a machine that has never had it, and saying so is better than
    a feature that quietly does nothing.
    """
    where = folder()
    if not where:
        return False, 'this platform has no Titan folder'
    parent = os.path.dirname(where)
    if not os.path.isdir(parent) and not os.path.isdir(where):
        return False, 'Titan is not installed on this machine'
    return True, ''


def _read(store):
    where = path(store)
    if not where or not os.path.exists(where):
        return {}
    try:
        with open(where, 'r', encoding='utf-8') as handle:
            found = json.load(handle)
        return found if isinstance(found, dict) else {}
    except Exception as error:                       # noqa: BLE001
        globals()['_last_error'] = '%s: %s' % (type(error).__name__, error)
        return {}


def _write(store, rows):
    where = path(store)
    if not where:
        return False
    try:
        os.makedirs(os.path.dirname(where), exist_ok=True)
        # Written beside and moved into place: a reader that is reading
        # this file while the other one writes it must never see half of
        # one.
        temporary = where + '.new'
        with open(temporary, 'w', encoding='utf-8') as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=1)
        os.replace(temporary, where)
        return True
    except Exception as error:                       # noqa: BLE001
        globals()['_last_error'] = '%s: %s' % (type(error).__name__, error)
        return False


# --------------------------------------------------------------------------- #
# Merging
# --------------------------------------------------------------------------- #
def _when(row):
    """When this row was written down. 0 when it does not say."""
    if not isinstance(row, dict):
        return 0
    for name in ('at', 'described_at', 'updated_at'):
        try:
            value = int(row.get(name) or 0)
        except (TypeError, ValueError):
            continue
        if value:
            return value
    return 0


def _typed_by_a_person(row):
    return isinstance(row, dict) and _text(row.get('source')) == 'user'


def better(mine, theirs):
    """Which of two rows for one control to keep, and why.

    ``(row, 'mine'|'theirs'|'same')``. Separated out and named because it
    is the whole of the merge and the one part worth being able to test on
    its own.
    """
    if mine is None:
        return theirs, 'theirs'
    if theirs is None:
        return mine, 'mine'
    # A name somebody typed beats one a model read off a picture, whichever
    # is newer: they looked at it and decided.
    mine_typed = _typed_by_a_person(mine)
    theirs_typed = _typed_by_a_person(theirs)
    if mine_typed != theirs_typed:
        return (mine, 'mine') if mine_typed else (theirs, 'theirs')
    when_mine, when_theirs = _when(mine), _when(theirs)
    if when_mine == when_theirs:
        return mine, 'same'
    return (mine, 'mine') if when_mine > when_theirs else (theirs, 'theirs')


def merge(mine, theirs):
    """Two whole stores into one. ``(merged, taken, given, conflicts)``.

    ``{program: {key: row}}`` both sides, which is the shape
    :mod:`labels` already keeps.
    """
    merged = {}
    taken = given = conflicts = 0
    programs = set(mine or {}) | set(theirs or {})
    for program in programs:
        ours = (mine or {}).get(program) or {}
        yours = (theirs or {}).get(program) or {}
        if not isinstance(ours, dict):
            ours = {}
        if not isinstance(yours, dict):
            yours = {}
        rows = {}
        for key in set(ours) | set(yours):
            one, whose = better(ours.get(key), yours.get(key))
            rows[key] = one
            if key in ours and key in yours and ours[key] != yours[key]:
                conflicts += 1
            if whose == 'theirs':
                taken += 1
            elif whose == 'mine' and key not in yours:
                given += 1
        if rows:
            merged[program] = rows
    return merged, taken, given, conflicts


# --------------------------------------------------------------------------- #
# Doing it
# --------------------------------------------------------------------------- #
def sync_labels():
    """Share what this reader knows about controls. ``(ok, sentence)``.

    Never on the focus path, never raises, and safe to call when Titan is
    not installed - it says so and changes nothing.
    """
    ready, why = available()
    if not ready:
        return False, why
    try:
        from . import labels
        mine = labels.everything()
    except Exception as error:                       # noqa: BLE001
        return False, '%s: %s' % (type(error).__name__, error)
    with _LOCK:
        theirs = _read('labels')
        merged, taken, given, conflicts = merge(mine, theirs)
        if not _write('labels', merged):
            return False, _last_error or 'the shared file could not be written'
        _counted['merged'] += 1
        _counted['taken'] += taken
        _counted['given'] += given
        _counted['conflicts'] += conflicts
    # And back into this reader's own store, so what the other one knew is
    # answered here without asking the shared file on every control.
    try:
        from . import labels
        brought = labels.take_shared(merged)
    except Exception:                                # noqa: BLE001
        brought = 0
    return True, ('shared %d control name(s); %d came from the other reader'
                  % (sum(len(rows) for rows in merged.values()), brought))


def report():
    ready, why = available()
    with _LOCK:
        found = dict(_counted)
    found.update({'available': ready, 'why': why, 'folder': folder(),
                  'last_error': _last_error})
    return found


def forget():
    with _LOCK:
        for name in _counted:
            _counted[name] = 0
        globals()['_last_error'] = ''
