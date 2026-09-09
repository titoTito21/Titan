# -*- coding: utf-8 -*-
"""A switch that means "here", not "everywhere".

The three AI-backed features - reading an unnamed control to name it,
reading a whole window as a picture, and AI OCR generally - are the ones a
user wants ON in one program and OFF in every other. A media player whose
toolbar is eleven unnamed buttons is worth a handful of requests once; a
browser is not, and a program the user is in all day certainly is not. One
global switch makes that choice for the whole machine, and the answer to
"should this send pictures of my screen to a provider" is different in
every program.

So each of them is answered per PROGRAM, and the global switch is what a
program with no answer of its own falls back to. Nothing here is a new
kind of setting: it is the same switches, asked with a window in mind.

**Keyed on the executable**, which is what a person means by "this
program": the file manager is `explorer.exe` whichever folder it is
showing, and a Titan application is its own process with its own name.
That is the same key :mod:`labels` files a control's name under, so a user
who has labelled controls in a program and switched labelling on for it
has both filed in the same place.

Kept in NVDA's own configuration folder, with the labels and the voice
classes, for the reason all three are: they are answers about how NVDA
should behave, they must survive Titan being uninstalled, and a user with
no Titan at all still has a reader that behaves the way they set it.
"""

import json
import os
import threading

#: The switches that can be answered per program. Deliberately only the
#: ones that SPEND something - a request, a picture of the screen leaving
#: the machine - because those are the ones whose right answer differs
#: from program to program. How a control is read is a preference and
#: belongs to the user, not to the window they happen to be in.
PER_PROGRAM = ('autoLabel', 'surfaceReading', 'graphicKinds', 'surfaceGame')

FILENAME = 'titanPerProgram.json'

_LOCK = threading.RLock()
_store = None


def _folder():
    try:
        import globalVars
        return globalVars.appArgs.configPath
    except Exception:                                # noqa: BLE001
        return ''


def path():
    folder = _folder()
    return os.path.join(folder, FILENAME) if folder else ''


def _load():
    global _store
    with _LOCK:
        if _store is not None:
            return _store
        _store = {}
        where = path()
        if where and os.path.isfile(where):
            try:
                with open(where, encoding='utf-8') as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    for program, answers in data.items():
                        if isinstance(answers, dict):
                            _store[str(program).lower()] = {
                                str(name): bool(value)
                                for name, value in answers.items()
                                if name in PER_PROGRAM}
            except Exception:                        # noqa: BLE001
                _store = {}
        return _store


def forget():
    global _store
    with _LOCK:
        _store = None


def save():
    where = path()
    if not where:
        return False
    with _LOCK:
        data = {program: dict(answers)
                for program, answers in _load().items() if answers}
    try:
        with open(where, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1,
                      sort_keys=True)
        return True
    except Exception:                                # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Which program
# --------------------------------------------------------------------------- #
def application_of(obj=None):
    """The program a window belongs to, or the one in front. '' for none."""
    if obj is None:
        obj = _focused()
    if obj is None:
        return ''
    from . import labels
    name = labels.application_of(obj)
    return '' if name == 'unknown' else name


def _focused():
    from . import compat
    api = compat.api
    if api is None:
        return None
    for ask in ('getFocusObject', 'getForegroundObject'):
        try:
            found = getattr(api, ask)()
        except Exception:                            # noqa: BLE001
            continue
        if found is not None:
            return found
    return None


def label_of(obj=None):
    """What to call this program to the user. Its own window's name first."""
    if obj is None:
        obj = _focused()
    try:
        title = str(getattr(obj, 'appModule', None)
                    and obj.appModule.appName or '').strip()
    except Exception:                                # noqa: BLE001
        title = ''
    return title or application_of(obj) or ''


# --------------------------------------------------------------------------- #
# Reading and changing one
# --------------------------------------------------------------------------- #
#: `surfaceGame` has no general setting of its own: whether a program is a
#: game is a fact about that program, not a preference. Its default comes
#: from the window class, and this only records a user who has said
#: otherwise.
NO_GENERAL_SETTING = ('surfaceGame',)


def _global(name):
    if name in NO_GENERAL_SETTING:
        return False
    from . import configSpec
    return bool(configSpec.read().get(name, False))


def answered(name, program):
    """Whether this program has an answer of its own for this switch."""
    if name not in PER_PROGRAM:
        return False
    return str(program or '').lower() in _load() and \
        name in _load()[str(program or '').lower()]


def value(name, obj=None):
    """The switch as it applies HERE: this program's answer, or the global.

    Never raises and never needs a window: asked about a control that has
    gone, or with no NVDA under it at all, it is the global answer - which
    is what the switch meant before any of this existed.
    """
    if name not in PER_PROGRAM:
        return _global(name)
    program = application_of(obj)
    if program:
        answers = _load().get(program)
        if answers is not None and name in answers:
            return bool(answers[name])
    return _global(name)


def set_value(name, program, wanted):
    """Answer one switch for one program."""
    if name not in PER_PROGRAM or not program:
        return False
    with _LOCK:
        _load().setdefault(str(program).lower(), {})[name] = bool(wanted)
    return save()


def clear(name, program):
    """Forget this program's answer, so the global switch decides again."""
    with _LOCK:
        answers = _load().get(str(program or '').lower())
        if not answers or name not in answers:
            return False
        answers.pop(name, None)
    return save()


def described(obj=None):
    """Every per-program switch as it stands for this program.

    ``[{'id', 'on', 'own', 'global'}]`` - ``own`` says whether the answer
    is this program's or the one it inherited, which is the difference the
    menu has to show or a user cannot tell why a switch they never touched
    is on.
    """
    program = application_of(obj)
    rows = []
    for name in PER_PROGRAM:
        rows.append({'id': name,
                     'on': value(name, obj),
                     'own': answered(name, program),
                     'global': _global(name)})
    return rows


def programs():
    """Every program that has an answer of its own."""
    return sorted(_load())
