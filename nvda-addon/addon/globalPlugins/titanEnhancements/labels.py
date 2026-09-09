# -*- coding: utf-8 -*-
"""Names for the controls a program never named.

A button with no accessible name is read as "button". A toolbar of eleven
of them is read as eleven buttons, and the only way to find the one that
saves is to press them and see. This is the oldest unfixed problem in
screen reading, and every reader has an answer to it: JAWS has custom
labels, NVDA has its own for the web. Both are the same shape - the user
labels the control by hand, once, and the reader remembers.

This is that, with two things added that follow from what Titan can do:

* **The label can be worked out rather than typed.** Titan has AI OCR, so a
  control that is drawn but not named can be READ - the caption printed on
  it is right there in the picture. Asked once, remembered for ever, and
  never asked again for the same control.
* **A reader module can carry labels**, so a program a module was written
  for arrives labelled instead of needing every user to label it again.

**What a label is attached to has to survive the program restarting**,
which rules out anything to do with where a window happens to be. The key
is the identity Windows itself keeps: the executable, the window class, the
control's own dialog id, and the automation id where there is one. The
position in the parent is the last resort and is marked as such, because a
toolbar that gains a button moves everything after it - a label that
followed position would end up on the wrong control, which is worse than no
label at all.

Nothing here needs Titan running. The AI half does, and says so; a label
already stored is answered with Titan switched off, uninstalled or never
installed, because by then it is a string in a file of the user's own.
"""

import json
import os
import threading
import time

#: The file, in NVDA's own configuration folder - so labels survive an
#: add-on update and are backed up with everything else the user has set.
FILENAME = 'titanLabels.json'

#: A label is a label, not a paragraph. What arrives from an AI reading of
#: a button is occasionally a sentence about the button, and a control
#: whose name is a sentence is a control the reader talks over.
MAX_LENGTH = 60

#: Where a label came from. It decides nothing about how it is spoken; it
#: decides what may overwrite it - the user's own is never replaced by a
#: guess.
SOURCES = ('user', 'module', 'ai')

_LOCK = threading.RLock()
_store = None
_path = ''


def _folder():
    try:
        import globalVars
        return globalVars.appArgs.configPath
    except Exception:                                # noqa: BLE001
        return ''


def path():
    global _path
    if _path:
        return _path
    folder = _folder()
    _path = os.path.join(folder, FILENAME) if folder else ''
    return _path


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
                    _store = {str(app): dict(rows) for app, rows
                              in data.items() if isinstance(rows, dict)}
            except Exception:                        # noqa: BLE001
                # A file that will not parse is not a reason to lose the
                # session: the labels are a convenience and the reader is
                # not. It is left on disk rather than overwritten, so
                # somebody can look at it.
                _store = {}
        return _store


def forget():
    """Throw away what is in memory - the next read goes to the file."""
    global _store
    with _LOCK:
        _store = None


def save():
    where = path()
    if not where:
        return False
    with _LOCK:
        data = json.loads(json.dumps(_load()))
    try:
        with open(where, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1,
                      sort_keys=True)
        return True
    except Exception:                                # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# What a label is attached to
# --------------------------------------------------------------------------- #
def _text(value):
    return str(value or '').strip()


def application_of(obj):
    """The program, as the key everything is filed under."""
    try:
        name = _text(getattr(getattr(obj, 'appModule', None), 'appName', ''))
    except Exception:                                # noqa: BLE001
        name = ''
    return name.lower() or 'unknown'


def _control_id(obj):
    try:
        import ctypes
        handle = int(getattr(obj, 'windowHandle', 0) or 0)
        if not handle:
            return 0
        return int(ctypes.windll.user32.GetDlgCtrlID(ctypes.c_void_p(handle)) or 0)
    except Exception:                                # noqa: BLE001
        return 0


def _index_in_parent(obj):
    try:
        return int(getattr(obj, 'indexInParent', -1))
    except Exception:                                # noqa: BLE001
        return -1


def key_of(obj):
    """A key for this control that survives the program being restarted.

    ``('', False)`` when there is nothing stable to hold on to. The second
    value says whether the key is a STRONG one - an automation id or a
    dialog control id, both of which are the program's own name for the
    control - or a weak one built from where the control sits, which moves
    the moment a toolbar gains a button.
    """
    if obj is None:
        return '', False
    parts = [_text(getattr(obj, 'windowClassName', '')),
             _text(getattr(getattr(obj, 'role', None), 'name', '')).upper()]
    automation = _text(getattr(obj, 'UIAAutomationId', ''))
    control = _control_id(obj)
    strong = bool(automation) or control > 0
    parts.append(automation or (str(control) if control > 0 else ''))
    if not strong:
        index = _index_in_parent(obj)
        if index < 0:
            return '', False
        parts.append('#%d' % index)
    key = '|'.join(part for part in parts if part is not None)
    return key, strong


# --------------------------------------------------------------------------- #
# Reading and writing one
# --------------------------------------------------------------------------- #
def get(obj):
    """The stored label for this control, or ''."""
    key, _strong = key_of(obj)
    if not key:
        return ''
    rows = _load().get(application_of(obj)) or {}
    row = rows.get(key)
    if isinstance(row, dict):
        return _text(row.get('label'))
    return _text(row)


def described(obj):
    """``(label, source)`` - what is stored and where it came from."""
    key, _strong = key_of(obj)
    if not key:
        return '', ''
    row = (_load().get(application_of(obj)) or {}).get(key)
    if isinstance(row, dict):
        return _text(row.get('label')), _text(row.get('source'))
    return _text(row), ''


def put(obj, label, source='user'):
    """Remember a label. The user's own is never overwritten by a guess."""
    label = _text(label)[:MAX_LENGTH]
    if not label:
        return False
    key, strong = key_of(obj)
    if not key:
        return False
    if source == 'ai' and not strong:
        # A guessed label on a key that moves is the one combination that
        # can end up naming the wrong control, so it is refused. A user who
        # types one has looked at it and may put it wherever they like.
        return False
    application = application_of(obj)
    with _LOCK:
        store = _load()
        rows = store.setdefault(application, {})
        existing = rows.get(key)
        if isinstance(existing, dict) and existing.get('source') == 'user' \
                and source != 'user':
            return False
        rows[key] = {'label': label, 'source': source if source in SOURCES
                     else 'user', 'at': int(time.time())}
    save()
    return True


def remove(obj):
    key, _strong = key_of(obj)
    if not key:
        return False
    with _LOCK:
        rows = _load().get(application_of(obj)) or {}
        if key not in rows:
            return False
        rows.pop(key, None)
    save()
    return True


def count():
    return sum(len(rows) for rows in _load().values())


def for_application(name):
    return dict(_load().get(_text(name).lower()) or {})


def needs_one(obj):
    """Whether this control is worth labelling at all.

    Only something with nothing to say for itself: no name, no value, no
    description. A control the program named is not improved by a second
    name, and a reader that offered to relabel everything would be
    offering the user a job.
    """
    if obj is None:
        return False
    for attribute in ('name', 'value', 'description'):
        try:
            if _text(getattr(obj, attribute, '')):
                return False
        except Exception:                            # noqa: BLE001
            continue
    key, _strong = key_of(obj)
    return bool(key)


def applies(obj, module=None):
    """``(label, source)`` - the name to READ for this control, or ``('', '')``.

    **The one place that decides whether a stored name is used**, and it is
    one place because it was two rules in one function and one of them was
    wrong: `_label_reading` began by asking :func:`needs_one`, which answers
    False for anything that has a name, a value or a description of its
    own - so renaming a control that HAD a name stored the name, said "this
    control is now called X", and read the old one for ever.

    The two rules are different and now say so:

    * A name the **user typed** applies whatever the control is called. They
      renamed it on purpose; a reader that then read the old name is a
      reader that ignored them.
    * A name **nobody asked for** - a reader module's, or one worked out
      from a picture - is only for a control with nothing to say for
      itself. A control the program named is not improved by a guess at it.
    """
    if obj is None:
        return '', ''
    label, source = described(obj)
    if label and source == 'user':
        return label, source
    if not needs_one(obj):
        return '', ''
    if label:
        return label, source
    if module is not None:
        try:
            key, _strong = key_of(obj)
            found = module.label_for(key)
            if found:
                return found, 'module'
        except Exception:                            # noqa: BLE001
            pass
    return '', ''
