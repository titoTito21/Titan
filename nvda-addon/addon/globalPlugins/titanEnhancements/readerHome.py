# -*- coding: utf-8 -*-
"""Where BOTH readers keep what the user taught them.

Every store a reader accumulates - the names given to controls, the voice
classes, the speech and sound schemes, the markers, the monitors, the
procedures, the per-program switches, the reader modules, the action
catalogue - is one file, byte-identical in the NVDA add-on and in Titan
Access. The FOLDER was not one: inside NVDA each module asked
``globalVars.appArgs.configPath`` (NVDA's own configuration folder) and
outside it ``.../titosoft/Titan/screenreader``, so a control named in one
reader was unknown to the other, a scheme chosen in one was not the scheme
in the other, and the two readers' stores had to be merged through a third
file (`shared.py`) to agree about anything at all.

This is the one answer: ``%APPDATA%/titosoft/Titan/accessibility``, in
both readers, always. What either reader learns is there for the other the
moment it is written.

Inside it: ``labels/<program>/labels.json`` for the names given to a
program's controls, ``window_data/<program>/<module>.json`` for what is
known about its windows, ``shared/`` for the stores the two readers merge,
and one file per store for the rest.

**What was already there is brought along, once.** A user who has named
forty controls and made three schemes in NVDA's folder must not open the
reader one day and find them gone. The first time the folder is asked
for, every store found in the old places - NVDA's configuration folder
when the reader is NVDA, Titan's ``screenreader`` folder either way - and
not yet in the new one is COPIED there. Copied, never moved: a store the
old code still reads stays readable, and nothing here can lose a file.
"""

import os
import shutil
import threading

_LOCK = threading.RLock()

#: The folder's own name under Titan's.
NAME = 'accessibility'

#: The stores carried over from the old folders. Files by exact name,
#: folders by name; a name here is the only way something moves.
STORE_FILES = (
    'titanLabels.json', 'titanVoiceClasses.json', 'titanSpeechSchemes.json',
    'titanSoundScheme.json', 'titanMarkers.json', 'titanMonitors.json',
    'titanProcedures.json', 'titanPerProgram.json', 'titanIcons.json',
    'titanActions.json',
)
#: Old folder name -> the folder it lives in now. The user's own reader
#: modules were `titanReaderModules/`; they are `window_data/` here, one
#: folder per program (`readerModules` sorts them in on the first read).
STORE_FOLDERS = {'titanReaderModules': 'window_data', 'shared': 'shared'}

_state = {'migrated': False}
_counted = {'carried': 0}


def titan_folder():
    """``.../titosoft/Titan`` - where Titan keeps everything of the user's.

    Worked out exactly as Titan Access works out its own settings folder:
    a second guess at where Titan keeps things is a second folder.
    """
    try:
        import platform
        system = platform.system()
    except Exception:                                # noqa: BLE001
        system = ''
    if system == 'Windows':
        base = os.getenv('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'titosoft', 'Titan')
    if system == 'Darwin':
        return os.path.join(os.path.expanduser('~'), 'Library',
                            'Application Support', 'titosoft', 'Titan')
    return os.path.join(os.path.expanduser('~'), '.config', 'titosoft',
                        'Titan')


def folder():
    """``.../titosoft/Titan/accessibility``, made and filled on first use.

    Never ``''``: a reader with nowhere to write is a reader that forgets,
    and there is always a home folder to answer with.
    """
    where = os.path.join(titan_folder(), NAME)
    with _LOCK:
        try:
            os.makedirs(where, exist_ok=True)
        except OSError:
            pass
        if not _state['migrated']:
            _state['migrated'] = True
            _carry_over(where)
    return where


def path(name):
    """One store's file in the folder."""
    return os.path.join(folder(), str(name))


def shared_folder():
    """``.../accessibility/shared`` - the stores both readers MERGE rather
    than simply read (`shared.py` / Titan Access's `shared_names.py`)."""
    where = os.path.join(folder(), 'shared')
    try:
        os.makedirs(where, exist_ok=True)
    except OSError:
        pass
    return where


def modules_folder():
    """``.../accessibility/window_data`` - what is known about programs'
    windows (the user's own reader modules), made on demand."""
    where = os.path.join(folder(), 'window_data')
    try:
        os.makedirs(where, exist_ok=True)
    except OSError:
        pass
    return where


def report():
    with _LOCK:
        found = dict(_counted)
    found.update({'folder': folder(), 'migrated': _state['migrated']})
    return found


# --------------------------------------------------------------------------- #
# Bringing the old stores along
# --------------------------------------------------------------------------- #
def legacy_folders():
    """Where the stores used to be, most recent first.

    NVDA's configuration folder only when this IS NVDA (there is no such
    module anywhere else); Titan's ``screenreader`` folder always - Titan
    Access wrote there, and so did the add-on on a machine with no NVDA.
    """
    found = []
    try:
        import globalVars
        where = str(globalVars.appArgs.configPath or '')
        if where:
            found.append(where)
    except Exception:                                # noqa: BLE001
        pass
    found.append(os.path.join(titan_folder(), 'screenreader'))
    return found


def _carry_over(target):
    """Copy every store the old folders have and the new one has not."""
    for old in legacy_folders():
        if not old or not os.path.isdir(old):
            continue
        try:
            same = os.path.normcase(os.path.abspath(old)) == \
                os.path.normcase(os.path.abspath(target))
        except Exception:                            # noqa: BLE001
            same = False
        if same:
            continue
        for name in STORE_FILES:
            source = os.path.join(old, name)
            wanted = os.path.join(target, name)
            if os.path.isfile(source) and not os.path.exists(wanted):
                _copy(source, wanted)
        for name, new_name in STORE_FOLDERS.items():
            source = os.path.join(old, name)
            wanted = os.path.join(target, new_name)
            if not os.path.isdir(source):
                continue
            try:
                os.makedirs(wanted, exist_ok=True)
                for entry in os.listdir(source):
                    one = os.path.join(source, entry)
                    there = os.path.join(wanted, entry)
                    if os.path.isfile(one) and not os.path.exists(there):
                        _copy(one, there)
            except OSError:
                continue


def _copy(source, target):
    try:
        shutil.copy2(source, target)
        with _LOCK:
            _counted['carried'] += 1
        return True
    except OSError:
        return False


def forget():
    """Tests: ask again next time."""
    with _LOCK:
        _state['migrated'] = False
        _counted['carried'] = 0
