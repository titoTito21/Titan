# -*- coding: utf-8 -*-
"""Control names the user gave the OTHER reader, known here too.

Somebody reading this desktop uses Titan Access, or NVDA with Titan's
add-on, or both - and what they accumulate is the same thing either way: a
control the program never named and they named themselves, a picture they
had read once, a note they wanted said. Two copies of that means the work
is done twice, and switching readers loses the half you are not in.

**The shared place is Titan's own**:
``%APPDATA%/titosoft/Titan/screenreader/shared/controlNames.json`` - beside
this reader's settings, which is where it belongs, because Titan Access is
the half that is always installed when Titan is. The NVDA add-on's
``shared.py`` writes the same file with the same rules; this is the reading
half.

Two things it will not do:

* **It is never asked on the focus path.** Reading a JSON file is
  milliseconds, and milliseconds on every control is a reader that got
  slower for no reason anybody can see. It is read once and kept, and
  re-read when the file's own timestamp says it moved - the same rule
  Titan's settings already follow.
* **It never overwrites what this reader was told directly.** A name from
  the shared file is a name the user gave, and so is one they gave here;
  where both exist, the newer wins, and a name somebody TYPED always beats
  one a model read off a picture.
"""

import json
import os
import platform
import threading

_LOCK = threading.RLock()

FILENAME = "controlNames.json"

#: How often the file's timestamp is looked at, at most. The file changes
#: when the other reader syncs, which is when it connects - not something
#: worth asking the disk about more than this.
STAT_INTERVAL = 5.0

_rows = None
_stamp = None
_looked = 0.0


def folder():
    """``…/titosoft/Titan/screenreader/shared``.

    Worked out the same way :mod:`settings_store` works out its own, and
    it has to stay that way: a second guess at where Titan keeps things is
    a second folder, and then nothing is shared at all.
    """
    system = platform.system()
    if system == "Windows":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
        base = os.path.join(base, "titosoft", "Titan")
    elif system == "Darwin":
        base = os.path.join(os.path.expanduser("~"), "Library",
                            "Application Support", "titosoft", "Titan")
    else:
        base = os.path.join(os.path.expanduser("~"), ".config",
                            "titosoft", "Titan")
    return os.path.join(base, "screenreader", "shared")


def path():
    return os.path.join(folder(), FILENAME)


def _stat():
    try:
        found = os.stat(path())
        return (found.st_mtime, found.st_size)
    except OSError:
        return None


def _load():
    """The shared names, re-read only when the file has really moved."""
    global _rows, _stamp, _looked
    import time
    now = time.time()
    with _LOCK:
        if _rows is not None and now - _looked < STAT_INTERVAL:
            return _rows
        _looked = now
        stamp = _stat()
        if _rows is not None and stamp == _stamp:
            return _rows
        _stamp = stamp
        if stamp is None:
            _rows = {}
            return _rows
        try:
            with open(path(), "r", encoding="utf-8") as handle:
                found = json.load(handle)
            _rows = found if isinstance(found, dict) else {}
        except Exception:                            # noqa: BLE001
            # A half-written file, or one from a newer add-on: answering
            # nothing is right, and a reader must not stop over it.
            _rows = {}
        return _rows


def _text(value):
    return str(value or "").strip()


def key_of(window_class, role, automation_id="", control_id=0,
           index_in_parent=-1):
    """The key the add-on files a control under.

    It has to be spelled EXACTLY as the other reader spells it, or the two
    stores are two stores that happen to share a file. The add-on's
    `labels.key_of` builds it as class | ROLE | (automation id or control
    id), with `#index` appended only when neither of those exists.
    """
    parts = [_text(window_class), _text(role).upper()]
    strong = _text(automation_id) or (str(control_id)
                                      if control_id and control_id > 0
                                      else "")
    parts.append(strong)
    if not strong:
        if index_in_parent is None or index_in_parent < 0:
            return ""
        parts.append("#%d" % int(index_in_parent))
    return "|".join(part for part in parts if part is not None)


def name_for(application, key):
    """The name the user gave this control in either reader, or ``""``."""
    if not key:
        return ""
    rows = _load().get(_text(application).lower()) or {}
    row = rows.get(key)
    if isinstance(row, dict):
        return _text(row.get("label"))
    return _text(row)


def description_for(application, key):
    """What a picture was read as - remembered, so it costs one request."""
    if not key:
        return ""
    rows = _load().get(_text(application).lower()) or {}
    row = rows.get(key)
    return _text(row.get("description")) if isinstance(row, dict) else ""


def custom_for(application, key):
    """What the user decided about this control: silent, its role word, a
    note, a voice. ``{}`` when they decided nothing."""
    if not key:
        return {}
    rows = _load().get(_text(application).lower()) or {}
    row = rows.get(key)
    if not isinstance(row, dict):
        return {}
    found = {}
    for name in ("silent", "role_word", "voice", "note"):
        if name in row:
            found[name] = row[name]
    return found


def count():
    return sum(len(rows) for rows in _load().values()
               if isinstance(rows, dict))


def report():
    """What is really being shared, for the settings page and a check."""
    where = path()
    return {"path": where, "there": os.path.exists(where),
            "programs": len(_load()), "controls": count()}


def forget():
    """Read it again next time - for the tests, and after a sync."""
    global _rows, _stamp, _looked
    with _LOCK:
        _rows = None
        _stamp = None
        _looked = 0.0
