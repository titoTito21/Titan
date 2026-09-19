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

#: One folder per program under ``.../accessibility/labels/``, each with
#: this file in it - so a program's labels can be looked at, copied to
#: another machine or given to somebody with the same program on their own.
SUBFOLDER = 'labels'
FILENAME = 'labels.json'
#: The one file everything used to be in, read once and split.
LEGACY_FILENAME = 'titanLabels.json'

#: A label is a label, not a paragraph. What arrives from an AI reading of
#: a button is occasionally a sentence about the button, and a control
#: whose name is a sentence is a control the reader talks over.
MAX_LENGTH = 60

#: A DESCRIPTION is the other thing, and the difference is what it is for.
#: A label stands in for the missing name and is said on every arrival, so
#: it has to be short. A description is a sentence the user asked for by
#: pressing a key - "describe this picture" - and is said only when they
#: ask. Keeping them apart is what stops a remembered sentence being read
#: out on every arrow key, which is what storing one as a label would do.
MAX_DESCRIPTION = 400

#: Where a label came from. It decides nothing about how it is spoken; it
#: decides what may overwrite it - the user's own is never replaced by a
#: guess.
SOURCES = ('user', 'module', 'ai')

_LOCK = threading.RLock()
_store = None
_path = ''


def _folder():
    """Where this reader keeps it: the folder BOTH readers share.

    `readerHome.folder()` - ``.../titosoft/Titan/accessibility`` in NVDA
    and in Titan Access alike, so what one reader learns the other has.
    It used to be NVDA's own configuration folder inside NVDA and Titan's
    ``screenreader`` folder outside it, which made this one file two
    stores; the old ones are carried over the first time it is asked.
    """
    try:
        from . import readerHome
        return readerHome.folder()
    except Exception:                                # noqa: BLE001
        return ''


def path():
    """The labels folder - ``.../accessibility/labels`` - one folder per
    application inside it, each holding that program's ``labels.json``.
    Answered as the folder because there is no longer one file."""
    global _path
    if _path:
        return _path
    folder = _folder()
    _path = os.path.join(folder, SUBFOLDER) if folder else ''
    return _path


def _safe_application(application):
    """A program's name as a folder name: what `application_of` answers is
    an executable's stem, but a stray character must not become a path."""
    name = _text(application).lower()
    for bad in '\\/:*?"<>|':
        name = name.replace(bad, '_')
    return name.strip('. ') or 'unknown'


def application_file(application):
    """Where one program's labels are kept."""
    where = path()
    if not where:
        return ''
    return os.path.join(where, _safe_application(application), FILENAME)


def _legacy_file():
    """The one file everything used to be in, brought over by `readerHome`."""
    folder = _folder()
    return os.path.join(folder, LEGACY_FILENAME) if folder else ''


def _read(where):
    try:
        with open(where, encoding='utf-8') as handle:
            data = json.load(handle)
    except Exception:                                # noqa: BLE001
        # A file that will not parse is not a reason to lose the session:
        # the labels are a convenience and the reader is not. It is left
        # on disk rather than overwritten, so somebody can look at it.
        return None
    return data if isinstance(data, dict) else None


def _load():
    global _store
    with _LOCK:
        if _store is not None:
            return _store
        _store = {}
        where = path()
        found_any = False
        if where and os.path.isdir(where):
            try:
                names = sorted(os.listdir(where))
            except OSError:
                names = []
            for name in names:
                one = os.path.join(where, name, FILENAME)
                if not os.path.isfile(one):
                    continue
                rows = _read(one)
                if rows is None:
                    continue
                found_any = True
                _store[str(name)] = dict(rows)
        if not found_any:
            # **The old single files, merged and split once.** Everything
            # used to be one `titanLabels.json` keyed by program - and
            # there were TWO of them, NVDA's and Titan Access's, each with
            # what that reader had learned. The first load that finds no
            # per-program folders reads every one it can find, keeps the
            # newest row where both name the same control, and the next
            # save writes it all out program by program. The old files are
            # left where they are, never deleted.
            for legacy in _legacy_files():
                data = _read(legacy) if os.path.isfile(legacy) else None
                if not data:
                    continue
                for app, rows in data.items():
                    if not isinstance(rows, dict):
                        continue
                    mine = _store.setdefault(str(app), {})
                    for key, row in rows.items():
                        _merge_row(mine, str(key), row)
        return _store


def _legacy_files():
    """The one-file stores of before, wherever they were kept."""
    found = []
    first = _legacy_file()
    if first:
        found.append(first)
    try:
        from . import readerHome
        for old in readerHome.legacy_folders():
            found.append(os.path.join(old, LEGACY_FILENAME))
    except Exception:                                # noqa: BLE001
        pass
    out = []
    for one in found:
        if one and one not in out:
            out.append(one)
    return out


def _merge_row(mine, key, row):
    """Keep the newer of two rows for one control; a row nobody else has
    is kept as it is."""
    have = mine.get(key)
    if not isinstance(row, dict):
        return
    if not isinstance(have, dict):
        mine[key] = dict(row)
        return
    try:
        newer = float(row.get('at') or 0) > float(have.get('at') or 0)
    except (TypeError, ValueError):
        newer = False
    if newer:
        mine[key] = dict(row)


def forget():
    """Throw away what is in memory - the next read goes to the files."""
    global _store, _path
    with _LOCK:
        _store = None
        _path = ''


def save():
    """Every program's labels into its own folder. True when all were."""
    where = path()
    if not where:
        return False
    with _LOCK:
        data = json.loads(json.dumps(_load()))
    wrote = True
    for application, rows in data.items():
        target = application_file(application)
        if not target:
            wrote = False
            continue
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, 'w', encoding='utf-8') as handle:
                json.dump(rows, handle, ensure_ascii=False, indent=1,
                          sort_keys=True)
        except Exception:                            # noqa: BLE001
            wrote = False
    return wrote


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


def description_of(obj):
    """``(text, kind)`` - what this picture was last read as, or ``('', '')``.

    **Remembered because a reading is a REQUEST.** A picture, an icon, a
    chart or an animation read with AI costs the user a call to their own
    provider and a picture of part of their screen sent to it; pressing
    the key on the same icon tomorrow should cost neither. This is filed
    exactly as a label is - under the program, against the identity
    Windows itself keeps - so it survives the program restarting, an
    add-on update and Titan not being installed at all.
    """
    key, _strong = key_of(obj)
    if not key:
        return '', ''
    row = (_load().get(application_of(obj)) or {}).get(key)
    if not isinstance(row, dict):
        return '', ''
    return _text(row.get('description')), _text(row.get('described_kind'))


def remember_description(obj, text, kind=''):
    """Keep what a picture was read as. ``False`` when there is no key.

    Stored on a WEAK key too, unlike a label: a label that lands on the
    wrong control renames it and is read out for ever, which is why a
    guessed one is refused there. A description is only ever said when
    the user asks for it, and asking again re-reads - so the worst a
    stale one can do is answer a question about the wrong picture once,
    which is what pressing the key twice already fixes.

    An ANIMATION is remembered like everything else, and is the one kind
    whose answer is a moment rather than a fact: it is what the picture
    showed when it was read. Pressing the key again is what asks for now.
    """
    text = _text(text)[:MAX_DESCRIPTION]
    if not text:
        return False
    key, _strong = key_of(obj)
    if not key:
        return False
    with _LOCK:
        rows = _load().setdefault(application_of(obj), {})
        row = rows.get(key)
        if not isinstance(row, dict):
            # A bare string is the oldest shape of a label; keep it.
            row = {'label': _text(row), 'source': 'user'} if row else {}
            rows[key] = row
        row['description'] = text
        row['described_kind'] = _text(kind)
        row['described_at'] = int(time.time())
    save()
    return True


def forget_description(obj):
    key, _strong = key_of(obj)
    if not key:
        return False
    with _LOCK:
        row = (_load().get(application_of(obj)) or {}).get(key)
        if not isinstance(row, dict) or 'description' not in row:
            return False
        for field in ('description', 'described_kind', 'described_at'):
            row.pop(field, None)
    save()
    return True


# --------------------------------------------------------------------------- #
# What is remembered about a PROGRAM rather than about one of its controls
# --------------------------------------------------------------------------- #
#: The bucket per-program notes live in. A key no control can have, because
#: `key_of` always joins its parts with "|".
NOTES = '__notes__'


def application_note(application, field):
    """Something remembered about the program itself, or ``''``.

    A window's icon is the PROGRAM's icon: one answer for every window it
    ever opens, so it is filed under the program and not under a control.
    """
    rows = _load().get(_text(application).lower()) or {}
    notes = rows.get(NOTES)
    if not isinstance(notes, dict):
        return ''
    return _text(notes.get(_text(field)))


def set_application_note(application, field, text):
    application = _text(application).lower()
    field = _text(field)
    text = _text(text)[:MAX_DESCRIPTION]
    if not application or not field:
        return False
    with _LOCK:
        rows = _load().setdefault(application, {})
        notes = rows.get(NOTES)
        if not isinstance(notes, dict):
            notes = {}
            rows[NOTES] = notes
        if text:
            notes[field] = text
        else:
            notes.pop(field, None)
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
    """How many LABELS are stored.

    Not how many rows: a row may now carry only a description, and the
    per-program notes are a row of their own. Counting those as labels
    would tell the user they had named controls they have never named.
    """
    total = 0
    for rows in _load().values():
        for key, row in rows.items():
            if key == NOTES:
                continue
            if isinstance(row, dict):
                total += 1 if _text(row.get('label')) else 0
            elif _text(row):
                total += 1
    return total


def description_count():
    total = 0
    for rows in _load().values():
        for key, row in rows.items():
            if key != NOTES and isinstance(row, dict) \
                    and _text(row.get('description')):
                total += 1
    return total


def for_application(name):
    """Every labelled control of this program - not the program's own notes."""
    rows = dict(_load().get(_text(name).lower()) or {})
    rows.pop(NOTES, None)
    return rows


# --------------------------------------------------------------------------- #
# What the user has decided about ONE control
# --------------------------------------------------------------------------- #
#: Everything that can be set on a single control, and what each does.
#: This is JAWS' customised control, which is thirty years old and still
#: the thing users of every other reader ask for: a control the program
#: got wrong is mended once, by the person it is wrong for, and stays
#: mended.
#:
#: Kept beside the label rather than in a store of its own, because it is
#: the same question about the same control - "what should this be to
#: me?" - and two files answering it would drift.
CUSTOM = {
    #: Never announced at all. For the control that is on every screen of
    #: a program and says nothing worth hearing.
    'silent': bool,
    #: Said instead of the control's type word. A "pane" the program uses
    #: as a toolbar is a toolbar to the person using it.
    'role_word': str,
    #: The semantic class its name is spoken in - see :mod:`classes`.
    'voice': str,
    #: Said after it, every time. The one thing a label cannot do: a
    #: label replaces the name, this adds to it.
    'note': str,
}

#: A note is said on every arrival, so it is held to a label's length
#: rather than a description's.
MAX_NOTE = 80


def custom_of(obj):
    """``{}`` or what the user has decided about this control.

    Only the fields they really set: a field that is absent is one the
    reader answers its own way, which is what makes this additive rather
    than a second description of every control.
    """
    key, _strong = key_of(obj)
    if not key:
        return {}
    row = (_load().get(application_of(obj)) or {}).get(key)
    if not isinstance(row, dict):
        return {}
    found = {}
    for name in CUSTOM:
        if name in row:
            found[name] = row[name]
    return found


def _clean_custom(field, value):
    """The value as it will be stored, or ``None`` to take the field off."""
    if field not in CUSTOM:
        return None
    if CUSTOM[field] is bool:
        return bool(value) if value is not None else None
    said = _text(value)
    if not said:
        return None
    return said[:MAX_NOTE if field == 'note' else MAX_LENGTH]


def customise(obj, **fields):
    """Set what the user has decided about this control.

    A field given as ``None`` or an empty string is taken OFF rather than
    stored empty, so "put it back to normal" is the same call as any
    other and there is no third state to get wrong.
    """
    key, _strong = key_of(obj)
    if not key:
        return False
    wanted = {name: value for name, value in fields.items() if name in CUSTOM}
    if not wanted:
        return False
    with _LOCK:
        rows = _load().setdefault(application_of(obj), {})
        row = rows.get(key)
        if not isinstance(row, dict):
            row = {'label': _text(row), 'source': 'user'} if row else {}
            rows[key] = row
        for name, value in wanted.items():
            cleaned = _clean_custom(name, value)
            if cleaned is None or cleaned is False:
                row.pop(name, None)
            else:
                row[name] = cleaned
        if not row:
            rows.pop(key, None)
    save()
    return True


def custom_count():
    total = 0
    for rows in _load().values():
        for key, row in rows.items():
            if key != NOTES and isinstance(row, dict) \
                    and any(name in row for name in CUSTOM):
                total += 1
    return total


def everything():
    """{program: {key: row}} - the whole store, for the manager.

    A copy, because the manager holds it while the user reads it and a
    reader that changed underneath them would be a list that moves.
    """
    return {name: dict(rows) for name, rows in _load().items()}


def take_shared(rows):
    """Bring in what the OTHER reader knows. How many rows were new.

    The merge itself is :mod:`shared`'s - this is only the writing back,
    and it keeps the same rule: a row this reader has already, and that
    the user typed, is not replaced.
    """
    if not isinstance(rows, dict):
        return 0
    brought = 0
    with _LOCK:
        store = _load()
        for application, theirs in rows.items():
            if not isinstance(theirs, dict):
                continue
            ours = store.setdefault(_text(application).lower(), {})
            for key, row in theirs.items():
                if key == NOTES and not isinstance(row, dict):
                    continue
                here = ours.get(key)
                if here == row:
                    continue
                if isinstance(here, dict) and here.get('source') == 'user' \
                        and not (isinstance(row, dict)
                                 and row.get('source') == 'user'):
                    continue
                ours[key] = row
                brought += 1
    if brought:
        save()
    return brought


def rename_key(application, key, label):
    """Rename a control the user is looking at in the manager.

    By KEY rather than by object, because in the manager there is no
    object: the control is in another program, possibly not running. The
    source becomes 'user' - they typed it, so nothing may overwrite it,
    which is the same rule :func:`put` follows.
    """
    application = _text(application).lower()
    key = _text(key)
    label = _text(label)[:MAX_LENGTH]
    if not application or not key:
        return False
    with _LOCK:
        rows = _load().get(application)
        if not isinstance(rows, dict) or key not in rows:
            return False
        row = rows[key]
        if not isinstance(row, dict):
            row = {}
            rows[key] = row
        if label:
            row['label'] = label
            row['source'] = 'user'
            row['at'] = int(time.time())
        else:
            # An empty name means "take the name off", which is not the
            # same as forgetting the row: a description may be the only
            # thing worth keeping about it.
            row.pop('label', None)
            row.pop('source', None)
            if not row:
                rows.pop(key, None)
    save()
    return True


def set_field(application, key, field, value):
    """Set one custom field on a control the manager is looking at.

    By KEY rather than by object, for the same reason :func:`rename_key`
    is: in the manager there is no object - the control is in another
    program, which may not even be running.
    """
    application = _text(application).lower()
    key = _text(key)
    if not application or not key or field not in CUSTOM:
        return False
    cleaned = _clean_custom(field, value)
    with _LOCK:
        rows = _load().get(application)
        if not isinstance(rows, dict) or key not in rows:
            return False
        row = rows[key]
        if not isinstance(row, dict):
            row = {'label': _text(row), 'source': 'user'} if row else {}
            rows[key] = row
        if cleaned is None or cleaned is False:
            row.pop(field, None)
        else:
            row[field] = cleaned
    save()
    return True


def remove_key(application, key):
    """Forget one row of one program, from the manager."""
    application = _text(application).lower()
    key = _text(key)
    if not application or not key:
        return False
    with _LOCK:
        rows = _load().get(application)
        if not isinstance(rows, dict) or key not in rows:
            return False
        rows.pop(key, None)
        if not rows:
            _load().pop(application, None)
    save()
    return True


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
