# -*- coding: utf-8 -*-
"""The command palette, walked exactly as a window is walked.

It was two modal dialogs - a list of layers, then a list of commands -
and a modal dialog is the one interaction on this desktop that is not
like the others: it takes the keyboard away from the reader, it is read
by NVDA as a dialog rather than by this add-on in the user's own voice
classes, and it plays none of the auditory icons every other list here
plays. A palette somebody opens twenty times a day should feel like the
virtual window, the terminal review and the widget review, because those
are the four things this add-on asks people to learn and they should be
one thing.

So this is a **list in the same shape as** :mod:`virtualWindow`: the up
and down arrows walk it with the same tone falling from the top of the
list to the bottom, Home and End are its ends, **Enter runs what the
cursor is on**, and **Escape goes back one level before it closes** - the
commands to the layers, the layers to the program the user was in.
Nothing is drawn and no window is opened at all, so it can be used over
any program without taking the foreground away from it.

A row is ``{'label', 'role', 'run'}`` and ``run`` is a callable, so this
knows nothing about what a command is - which is what keeps the table of
commands in :mod:`layers` the one place they are written down.
"""

import threading

from . import compat
from . import i18n
from . import icons

_ = i18n.install(globals())

_LOCK = threading.RLock()

#: ``rows`` are what is being walked, ``back`` is what Escape does before
#: it closes, and ``title`` is what the level is called.
_state = {'on': False, 'rows': [], 'at': 0, 'title': '', 'back': None}

_counted = {'opened': 0, 'ran': 0, 'went_back': 0, 'closed': 0}


def _text(value):
    return str(value or '').strip()


def walking():
    """Whether the palette has the keys right now."""
    with _LOCK:
        return bool(_state['on'])


#: :mod:`reviews` asks every key-borrowing mode this, by this name, so
#: that starting one ends the others. The palette shares their arrows, so
#: it is one of them whatever it is called.
reviewing = walking


def report():
    with _LOCK:
        found = dict(_counted)
        found.update({'walking': _state['on'], 'rows': len(_state['rows']),
                      'at': _state['at'], 'level': _state['title']})
    return found


# --------------------------------------------------------------------------- #
# Saying
# --------------------------------------------------------------------------- #
def _say(text):
    if compat.queueHandler is None or compat.ui is None:
        return

    def speak():
        try:
            compat.ui.message(text)
        except Exception:                            # noqa: BLE001
            pass
    compat.queueHandler.queueFunction(compat.queueHandler.eventQueue, speak)


def _say_parts(parts):
    """The row in the user's own semantic classes, as every other list
    here is said - the name at its own tone, what it IS lower, where it
    is in the list higher."""
    if not parts:
        return
    try:
        from . import elements
        sequence = elements.sequence(parts)
    except Exception:                                # noqa: BLE001
        sequence = None
    if not sequence or compat.speech is None:
        _say(', '.join(str(text) for text, _voice in parts))
        return
    try:
        from . import voices
        voices.speak_sequence(sequence)
    except Exception:                                # noqa: BLE001
        _say(', '.join(str(text) for text, _voice in parts))


def _beep(at, count):
    """Where in the list the cursor is, as a tone. The same curve the
    virtual window uses, because they are the same gesture."""
    if compat.tones is None:
        return
    span = max(1, (count or 1) - 1)
    where = max(0.0, min(1.0, at / float(span)))
    try:
        compat.tones.beep(int(1650 - 1230 * where), 22)
    except Exception:                                # noqa: BLE001
        pass


def _edge():
    if compat.tones is None:
        return
    try:
        compat.tones.beep(220, 30)
    except Exception:                                # noqa: BLE001
        pass


def _nothing():
    # Translators: said when there is nothing at the cursor.
    return False, _('Nothing here')


def here():
    with _LOCK:
        rows = _state['rows']
        at = _state['at']
    return rows[at] if 0 <= at < len(rows) else None


def parts_of(row, at=0, count=0):
    """``[(text, voice class)]`` for one row."""
    parts = [(_text(row.get('label')), 'name')]
    kind = _text(row.get('role'))
    if kind:
        parts.append((kind, 'kind'))
    if count > 1:
        # Translators: where a row is in a list. {at} is its number,
        # {count} how many there are.
        parts.append((_('{at} of {count}').format(at=at + 1, count=count),
                      'place'))
    return parts


def say_here(beep=True):
    row = here()
    if row is None:
        return _nothing()
    with _LOCK:
        at = _state['at']
        count = len(_state['rows'])
    if beep and not icons.play(_text(row.get('icon')) or 'list-item'):
        _beep(at, count)
    parts = parts_of(row, at=at, count=count)
    _say_parts(parts)
    return True, ', '.join(text for text, _voice in parts)


# --------------------------------------------------------------------------- #
# Walking
# --------------------------------------------------------------------------- #
def show(rows, title, back=None):
    """Put a level up and read its first row. ``(ok, said)``."""
    rows = [row for row in (rows or []) if _text(row.get('label'))]
    if not rows:
        return _nothing()
    from . import reviews
    reviews.stop_others('palette')
    with _LOCK:
        first = not _state['on']
        _state.update({'on': True, 'rows': rows, 'at': 0,
                       'title': _text(title), 'back': back})
        _counted['opened'] += 1
    if first:
        icons.play('open-object')
    if title:
        _say(_text(title))
    say_here()
    return True, ''


def move(delta):
    with _LOCK:
        rows = _state['rows']
        if not rows:
            return _nothing()
        at = _state['at'] + delta
        if at < 0 or at >= len(rows):
            _edge()
            return say_here(beep=False)
        _state['at'] = at
    return say_here()


def move_end(to_end):
    with _LOCK:
        rows = _state['rows']
        if not rows:
            return _nothing()
        _state['at'] = len(rows) - 1 if to_end else 0
    return say_here()


def activate():
    """Run the row the cursor is on. ``(ok, said)``."""
    row = here()
    if row is None:
        return _nothing()
    run = row.get('run')
    if not callable(run):
        return _nothing()
    with _LOCK:
        _counted['ran'] += 1
    return run()


def back():
    """One level up, or close. ``(ok, said)``.

    Escape means "out of this", not "out of everything": choosing the
    wrong layer should cost one keystroke rather than the whole palette.
    """
    with _LOCK:
        where = _state['back']
    if callable(where):
        with _LOCK:
            _counted['went_back'] += 1
        return where()
    return stop()


def stop():
    with _LOCK:
        was = _state['on']
        _state.update({'on': False, 'rows': [], 'at': 0, 'title': '',
                       'back': None})
        if was:
            _counted['closed'] += 1
    if was:
        icons.play('close-object')
    # Translators: said when the command palette is closed.
    return False, _('Palette closed')


def forget():
    """For the tests."""
    with _LOCK:
        _state.update({'on': False, 'rows': [], 'at': 0, 'title': '',
                       'back': None})
        for key in _counted:
            _counted[key] = 0
