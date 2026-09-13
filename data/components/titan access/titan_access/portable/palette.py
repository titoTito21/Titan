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

**And it has the virtual window's layouts and its corners**, because the
user asked for one way of reading everything here. The layout is the
virtual window's own setting (:func:`virtualWindow.layout`), so Numpad 4
and 6 change it for both at once: in the simple layout Left and Right
read a row by character; on the screen layout they go to the WORD beside
this one, which is what sits beside what on a line of text; and in the
interaction layout they go to the row beside this one, Down steps INTO
the row - its words, then its characters - and Up steps back out, said as
"In, <it>" and "Out of, <it>". Numpad 7, 9, 1 and 3 are the four corners
of the page: the start and the end of the first row, the start and the
end of the last.

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
_state = {'on': False, 'rows': [], 'at': 0, 'title': '', 'back': None,
          'letter': 0, 'inner': 0, 'depth': None,
          'kind': ''}

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


def say_here(beep=True, prefix=None):
    """Say the row the cursor is on. ``prefix`` is ``[(text, class)]``
    said in front of it, in the same utterance."""
    row = here()
    if row is None:
        return _nothing()
    with _LOCK:
        at = _state['at']
        count = len(_state['rows'])
    if beep and not icons.play(_text(row.get('icon')) or 'list-item'):
        _beep(at, count)
    parts = list(prefix or []) + parts_of(row, at=at, count=count)
    _say_parts(parts)
    return True, ', '.join(text for text, _voice in parts)


# --------------------------------------------------------------------------- #
# Walking
# --------------------------------------------------------------------------- #
def show(rows, title, back=None, kind='', at=0):
    """Put a level up and read its first row. ``(ok, said)``.

    ``kind`` is what this level IS - ``'text'`` for an answer being read,
    empty for a list of things to choose. It decides what is said on the
    way in and on the way out, and nothing else.

    ``at`` is which row the cursor lands on. It is 0 for a level being
    opened, and it is what a level being **put back** passes: somebody who
    went into a setting, answered it and came out belongs on the setting
    they answered, not at the top of a list of forty. A number that is not
    a row is the first row, so a list that has since got shorter cannot
    land the cursor on nothing.
    """
    rows = [row for row in (rows or []) if _text(row.get('label'))]
    if not rows:
        return _nothing()
    from . import reviews
    reviews.stop_others('palette')
    try:
        at = int(at)
    except (TypeError, ValueError):
        at = 0
    if not 0 <= at < len(rows):
        at = 0
    with _LOCK:
        first = not _state['on']
        _state.update({'on': True, 'rows': rows, 'at': at,
                       'title': _text(title), 'back': back,
                       'letter': 0, 'inner': 0, 'depth': None,
                       'kind': _text(kind)})
        _counted['opened'] += 1
    if first:
        icons.play('open-object')
    if title:
        _say(_text(title))
    if kind == 'text':
        # **An answer says that it IS one.** Somebody who asked a
        # question and is handed a list needs to know they are in the
        # answer rather than in a menu - and that Escape is how they
        # leave it. The pair has to be symmetrical or they have to
        # listen to work out which state they are in.
        # Translators: said on opening a long answer as a page to walk.
        _say(_('Message'))
    say_here()
    return True, ''


def _layout():
    """Which layout is on - the virtual window's, so that Numpad 4 and 6
    mean the same thing in every walked list. 'linear' where there is no
    virtual window to ask."""
    try:
        from . import virtualWindow
        return virtualWindow.layout()
    except Exception:                                # noqa: BLE001
        return 'linear'


def layout_cycle(delta=1):
    """The next or previous layout, for every walked list at once."""
    try:
        from . import virtualWindow
        return virtualWindow.layout_cycle(delta)
    except Exception:                                # noqa: BLE001
        return _nothing()


def move(delta):
    if _layout() == 'interact':
        return interact_in() if delta > 0 else interact_out()
    with _LOCK:
        rows = _state['rows']
        if not rows:
            return _nothing()
        at = _state['at'] + delta
        if at < 0 or at >= len(rows):
            _edge()
            return say_here(beep=False)
        _state['at'] = at
        _state['letter'] = 0
        _state['inner'] = 0
    return say_here()


def move_end(to_end):
    depth = _depth()
    if depth:
        # Inside a row in the interaction layout, Home and End are the
        # ends of what is being walked - its words or its characters.
        text = _label(here())
        words = _words()
        with _LOCK:
            if depth == 'chars':
                _state['letter'] = max(len(text) - 1, 0) if to_end else 0
                said = text[_state['letter']] if text else ''
            else:
                _state['inner'] = max(len(words) - 1, 0) if to_end else 0
                _state['letter'] = 0
                said = words[_state['inner']] if words else ''
        _say(said)
        return True, said
    with _LOCK:
        rows = _state['rows']
        if not rows:
            return _nothing()
        _state['at'] = len(rows) - 1 if to_end else 0
        _state['inner'] = 0
        _state['letter'] = 0
    return say_here()


def move_corner(dx_sign, dy_sign):
    """A corner of the page - Numpad 7, 9, 1 and 3, as in the virtual window.

    A list has no screen layout, but it has a SHAPE: the first row is its
    top and the last row its bottom, and a row runs from its first word
    to its last. So the left corners are the start of the first and the
    last row, said whole, and the right corners are the END of those rows
    - the last word, with the cursor left on it so Left reads back from
    there - which for a message is the end of its first and its last
    line, the four places a sighted reader's eye jumps to.
    """
    with _LOCK:
        rows = _state['rows']
        if not rows:
            return _nothing()
        _state['at'] = len(rows) - 1 if dy_sign > 0 else 0
        _state['inner'] = 0
        _state['letter'] = 0
        _state['depth'] = None
    name = corner_name(dx_sign, dy_sign)
    if dx_sign <= 0:
        return say_here(prefix=[(name, 'place')])
    return _say_end(prefix=[(name, 'place')])


def corner_name(dx_sign, dy_sign):
    """What a corner is called - the virtual window's own words."""
    try:
        from . import virtualWindow
        return virtualWindow.corner_name(dx_sign, dy_sign)
    except Exception:                                # noqa: BLE001
        return ''


def _say_end(prefix=None):
    """The end of the row: its last word, and where the row is."""
    row = here()
    text = _label(row)
    words = _words()
    if not words:
        return say_here(prefix=prefix)
    with _LOCK:
        at = _state['at']
        count = len(_state['rows'])
        _state['inner'] = len(words) - 1
        _state['letter'] = max(len(text) - 1, 0)
    _beep(at, count)
    parts = list(prefix or []) + [(words[-1], 'name')]
    if count > 1:
        parts.append((_('{at} of {count}').format(at=at + 1, count=count),
                      'place'))
    _say_parts(parts)
    return True, ', '.join(part for part, _voice in parts)


def move_across(delta):
    """The plain Left and Right, by layout: a character in the simple
    layout, the word beside this one on the screen layout, and the row
    beside this one in the interaction layout - or its words and
    characters once it has been stepped into."""
    which = _layout()
    if which == 'screen':
        return _word_bounded(delta)
    if which == 'interact':
        return move_sibling(delta)
    return move_char(delta)


def move_across_shift(delta):
    """Shift with Left and Right: the word beside this one in the simple
    layout, a character on the other two - whichever the plain arrows
    are not doing."""
    if _layout() == 'linear':
        return _word_bounded(delta)
    return move_char(delta)


def _label(row):
    return str((row or {}).get('label') or '')


def move_char(delta):
    """Left and Right: one character of the row's label, so a long command
    name reads letter by letter - the same as the virtual window."""
    row = here()
    if row is None:
        return _nothing()
    text = _label(row)
    if not text:
        return say_here(beep=False)
    with _LOCK:
        at = int(_state.get('letter') or 0) + int(delta)
        if at < 0 or at >= len(text):
            _edge()
            at = max(0, min(at, len(text) - 1))
        _state['letter'] = at
    said = text[at]
    _say(said)
    return True, said


def move_word(delta):
    """Control with Left and Right: one word of the row's label."""
    row = here()
    if row is None:
        return _nothing()
    words = [word for word in _label(row).split() if word]
    if not words:
        return move_char(delta)
    with _LOCK:
        at = int(_state.get('inner') or 0) + int(delta)
        if at < 0 or at >= len(words):
            return move_char(delta)
        _state['inner'] = at
        _state['letter'] = 0
    _say(words[at])
    return True, words[at]


def _words():
    return [word for word in _label(here()).split() if word]


def explore(x, y):
    """A finger on the pad, on a list that has no geometry.

    The screen's height is mapped onto the rows - the top of the pad is
    the first row, the bottom the last - so a list of twenty commands is
    twenty bands a finger can run down. Said only when the finger crosses
    into another row. ``(ok, said)``.
    """
    with _LOCK:
        rows = _state['rows']
        if not rows:
            return False, ''
        count = len(rows)
    try:
        from . import touchWalk
        _width, height = touchWalk.screen_size()
    except Exception:                                # noqa: BLE001
        height = 1080
    at = int(max(0, min(int(y), height - 1)) * count / float(max(height, 1)))
    at = max(0, min(at, count - 1))
    with _LOCK:
        if _state.get('explored') == at and _state['at'] == at:
            return True, ''
        _state['explored'] = at
        _state['at'] = at
        _state['inner'] = 0
        _state['letter'] = 0
        _state['depth'] = None
    return say_here()


def _word_bounded(delta):
    """One word of the row, stopping at its ends with the edge tone -
    for the layouts where a word is the thing beside a word."""
    row = here()
    if row is None:
        return _nothing()
    words = _words()
    if not words:
        return move_char(delta)
    with _LOCK:
        at = int(_state.get('inner') or 0) + int(delta)
        if at < 0 or at >= len(words):
            _edge()
            at = max(0, min(at, len(words) - 1))
        _state['inner'] = at
        _state['letter'] = 0
    _say(words[at])
    return True, words[at]


# --------------------------------------------------------------------------- #
# The interaction layout: Left and Right along the rows, Down into one,
# Up back out
# --------------------------------------------------------------------------- #
def _depth():
    """None for the row itself, 'words' or 'chars' once inside it. It
    belongs to the row it was set on, so landing on another row is back
    at the row without every move having to say so."""
    with _LOCK:
        depth = _state.get('depth')
        at = _state['at']
    if isinstance(depth, tuple) and len(depth) == 2 and depth[1] == at:
        return depth[0]
    return None


def _set_depth(level):
    with _LOCK:
        _state['depth'] = (level, _state['at']) if level else None


def _say_in(name, rest):
    # Translators: said on stepping INTO a row in the interaction layout.
    # {name} is the row; what follows is the first thing in it.
    _say_parts([(_('In {name}').format(name=name), 'place')] + list(rest))


def _say_out(name, rest):
    # Translators: said on stepping OUT of a row in the interaction layout.
    # {name} is the row that was left.
    _say_parts([(_('Out of {name}').format(name=name), 'place')]
               + list(rest))


def move_sibling(delta):
    """Left and Right in the interaction layout: the row beside this
    one, or the word or character beside this one once inside a row."""
    depth = _depth()
    if depth == 'chars':
        return move_char(delta)
    if depth == 'words':
        return _word_bounded(delta)
    with _LOCK:
        rows = _state['rows']
        if not rows:
            return _nothing()
        at = _state['at'] + delta
        if at < 0 or at >= len(rows):
            _edge()
            return say_here(beep=False)
        _state['at'] = at
        _state['inner'] = 0
        _state['letter'] = 0
    return say_here()


def interact_in():
    """Down in the interaction layout: into this row - its words, then
    the characters of the word the cursor is on."""
    row = here()
    if row is None:
        return _nothing()
    depth = _depth()
    if depth == 'chars':
        _edge()
        return say_here(beep=False)
    words = _words()
    if depth == 'words':
        with _LOCK:
            inner = int(_state.get('inner') or 0)
        word = words[inner] if 0 <= inner < len(words) else ''
        if not word:
            _edge()
            return say_here(beep=False)
        with _LOCK:
            _state['letter'] = max(_label(row).find(word), 0)
        _set_depth('chars')
        _say_in(word, [(word[0], 'name')])
        return True, word[0]
    if not words:
        _edge()
        return say_here(beep=False)
    with _LOCK:
        _state['inner'] = 0
        _state['letter'] = 0
    _set_depth('words')
    _say_in(_label(row), [(words[0], 'name')])
    return True, words[0]


def interact_out():
    """Up in the interaction layout: back out, step for step."""
    row = here()
    if row is None:
        return _nothing()
    depth = _depth()
    if depth == 'chars':
        words = _words()
        with _LOCK:
            inner = int(_state.get('inner') or 0)
        word = words[inner] if 0 <= inner < len(words) else ''
        _set_depth('words')
        _say_out(word, [(word, 'name')])
        return True, word
    if depth == 'words':
        _set_depth(None)
        with _LOCK:
            at = _state['at']
            count = len(_state['rows'])
        _say_out(_label(row), parts_of(row, at=at, count=count))
        return True, _label(row)
    _edge()
    return say_here(beep=False)


def activate():
    """Run the row the cursor is on. ``(ok, said)``."""
    row = here()
    if row is None:
        return _nothing()
    run = row.get('run')
    if not callable(run):
        # A row that only says something - a line of an answer being read
        # rather than a command - is not a failure to press. Saying it
        # again is what Enter means on a line of text.
        return say_here(beep=False)
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
        kind = _text(_state.get('kind'))
        _state.update({'on': False, 'rows': [], 'at': 0, 'title': '',
                       'back': None, 'kind': ''})
        if was:
            _counted['closed'] += 1
    if was:
        icons.play('close-object')
    if kind == 'text':
        # Translators: said when a long answer being walked is closed.
        # The pair with 'Message'.
        return False, _('Closing message')
    # Translators: said when the command palette is closed.
    return False, _('Palette closed')


def page(text, title='', back=None):
    """A long answer as something to WALK, rather than something said.

    **This is what stops an answer being interrupted.** Titan's own
    status, what it can do, what an application said, the journal - all
    of them are paragraphs, and a paragraph handed to `ui.message` is one
    utterance that the next focus event cancels halfway through. A reader
    that answers a question and is cut off has not answered it.

    So the answer becomes a list of its own lines, walked with the same
    arrows as everything else here, said one line at a time and re-said
    by pressing Enter. Escape closes it, or goes back a level where there
    is one.
    """
    lines = [one.rstrip() for one in str(text or '').splitlines()]
    rows = [{'label': one, 'role': ''} for one in lines if one.strip()]
    if not rows:
        return _nothing()
    return show(rows, title, back=back, kind='text')


def forget():
    """For the tests."""
    with _LOCK:
        _state.update({'on': False, 'rows': [], 'at': 0, 'title': '',
                       'back': None, 'kind': ''})
        for key in _counted:
            _counted[key] = 0
