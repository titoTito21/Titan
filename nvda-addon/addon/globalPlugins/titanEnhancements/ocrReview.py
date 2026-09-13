# -*- coding: utf-8 -*-
"""The recognised screen, walked with the arrow keys - and Enter clicks it.

Reading a window with OCR gives you the words. Every reader that does it -
NVDA's own, ZDSR's, JAWS' - then hands you a document you can read, and that
is where it stops: the words are text, and the thing they were written on is
gone. You cannot press what you just read.

This is the terminal review (:mod:`terminal`) applied to a recognised
screen, and it works because :mod:`localOcr` keeps **where every line and
every word is** in real screen coordinates. So:

* **Up and Down are lines, Left and Right are words**, Home and End the ends
  of the line, Page Up and Page Down a screenful - the same keys, in the
  same places, as the terminal review, because a user should learn one set
  of keys and not two.
* **Each line is marked by a short beep pitched by where it is on the
  screen**, top high and bottom low. In a window of forty lines that is the
  difference between knowing roughly where you are and counting.
* **Enter clicks where the cursor is.** Not "activates the control" - there
  is no control; there is a place on the screen where those words are drawn,
  and clicking it is exactly what a sighted person would do. That is the
  whole reason to keep the coordinates.

**The keys are borrowed, never stolen**, on the same discipline as
everywhere else here: bound only while the review is really up, given back
the moment it is not, and any key this does not use passed straight through.
"""

import threading

from . import compat
from . import i18n

_ = i18n.install(globals())

#: The beep that says where the line is - the terminal review's own band, so
#: the two sound like one feature.
FREQ_TOP = 1650
FREQ_BOTTOM = 420
BEEP_MS = 22

#: How many lines a page key moves, and what the beep's pitch is measured
#: against.
VISIBLE = 25

_LOCK = threading.RLock()
_state = {'on': False, 'row': 0, 'word': 0, 'rows': [], 'lines': [],
          'hwnd': 0, 'moves': 0, 'clicks': 0}


def report():
    with _LOCK:
        return {'reviewing': _state['on'], 'row': _state['row'],
                'word': _state['word'], 'lines': len(_state['rows']),
                'moves': _state['moves'], 'clicks': _state['clicks']}


def reviewing():
    with _LOCK:
        return bool(_state['on'])


# --------------------------------------------------------------------------- #
# Starting and stopping
# --------------------------------------------------------------------------- #
def toggle(hwnd=0):
    if reviewing():
        return stop()
    return start(hwnd)


def start(hwnd=0):
    """Read the window and walk it. ``(ok, sentence)``."""
    from . import localOcr
    ok, why = localOcr.available()
    if not ok:
        return False, why
    if not hwnd:
        hwnd = _the_guest_in(_foreground())
    if not hwnd:
        # Translators: said when there is no window to read.
        return False, _('There is no window to read')
    reading = localOcr.read_window(hwnd)
    if reading is None or not reading:
        return False, (localOcr.report().get('why')
                       # Translators: said when Windows read nothing.
                       or _('Windows read nothing in that window'))
    # Only once the recogniser has really answered: ending the other
    # reviews for one that then refused would lose the user the review
    # they were in and give them nothing.
    from . import reviews
    reviews.stop_others('ocrReview')
    with _LOCK:
        _state.update({'on': True, 'row': 0, 'word': 0, 'hwnd': int(hwnd),
                       'rows': reading.rows(), 'lines': list(reading.lines)})
    _cue(True)
    say_line(beep=True, interrupt=False)
    # Translators: said when the OCR review starts.
    return True, _('Screen review on')


def stop():
    was = reviewing()
    with _LOCK:
        _state.update({'on': False, 'rows': [], 'lines': []})
    if was:
        _cue(False)
    # Translators: said when the OCR review ends.
    return False, _('Screen review off')


def refresh():
    """Read the window again, keeping where the cursor is if it still fits."""
    with _LOCK:
        hwnd, row, word = _state['hwnd'], _state['row'], _state['word']
    if not reviewing():
        return False, _('Screen review off')
    from . import localOcr
    reading = localOcr.read_window(hwnd)
    if reading is None or not reading:
        # Translators: said when a re-read found nothing.
        return False, _('Nothing could be read this time')
    with _LOCK:
        _state['rows'] = reading.rows()
        _state['lines'] = list(reading.lines)
        _state['row'] = max(0, min(row, len(_state['rows']) - 1))
        _state['word'] = max(0, min(word, len(_words()) - 1))
    say_line(beep=True)
    # Translators: said when the screen has been read again. {n} is how many
    # lines it found.
    return True, _('{n} lines').format(n=len(reading.rows()))


def _the_guest_in(hwnd):
    """On a virtual machine, review the GUEST's screen, not VMware's window.

    **This is what a reader has to do while an operating system is being
    installed**, and it is the case no agent can ever answer: there is no
    guest operating system yet, no accessibility layer, no tools and nothing
    to run a program in - there is an installer painting text on a screen.
    From here that screen is a picture, and a picture is exactly what this
    review walks.

    The foreground window is the virtual machine's FRAME, whose top is
    VMware's own menu bar, tab strip and status line - controls NVDA reads
    properly already, and a recogniser reading them again is thirty lines of
    somebody else's furniture in front of the installer. The guest is
    painted on a child window of its own (`MKSEmbedded`), which
    `surface.display_of` already knows how to find, and reading THAT is 9 ms
    of the window's own device context.

    Every rectangle stays in screen coordinates, so Enter still clicks where
    the words really are - which in a graphical installer is how Next is
    pressed.
    """
    if not hwnd:
        return hwnd
    try:
        from . import compat
        from . import guest
        from . import surface
        api = compat.api
        obj = api.getForegroundObject() if api is not None else None
        if obj is None or not surface.is_virtual_machine(obj):
            return hwnd
        _where, handle = guest.display_of(obj)
        return handle or hwnd
    except Exception:                                # noqa: BLE001
        return hwnd


def _foreground():
    try:
        import ctypes
        ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
        return int(ctypes.windll.user32.GetForegroundWindow() or 0)
    except Exception:                                # noqa: BLE001
        return 0


def _cue(on):
    try:
        from . import earcons
        earcons.play_named('vscreenOn.ogg' if on else 'vscreenOff.ogg')
    except Exception:                                # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# Moving
# --------------------------------------------------------------------------- #
def _words(row=None):
    """The words of one line, each with its own rectangle."""
    with _LOCK:
        lines = _state['lines']
        at = _state['row'] if row is None else row
    return lines[at] if 0 <= at < len(lines) else []


def move_line(delta):
    with _LOCK:
        rows = _state['rows']
        if not rows:
            return False
        row = _state['row'] + delta
        edge = row < 0 or row >= len(rows)
        _state['row'] = max(0, min(row, len(rows) - 1))
        _state['word'] = 0
        _state['moves'] += 1
    if edge:
        _edge()
    say_line(beep=True)
    return True


def move_page(direction):
    return move_line(direction * VISIBLE)


def move_word(delta):
    words = _words()
    if not words:
        return False
    with _LOCK:
        word = _state['word'] + delta
        edge = word < 0 or word >= len(words)
        _state['word'] = max(0, min(word, len(words) - 1))
        at = _state['word']
        _state['moves'] += 1
    if edge:
        _edge()
    _say(words[at]['text'])
    return True


def move_end(to_end):
    words = _words()
    if not words:
        return False
    with _LOCK:
        _state['word'] = len(words) - 1 if to_end else 0
        at = _state['word']
        _state['moves'] += 1
    _say(words[at]['text'])
    return True


def say_line(beep=False, interrupt=True):
    with _LOCK:
        rows = _state['rows']
        row = _state['row']
    if beep:
        _beep(row)
    if not 0 <= row < len(rows):
        return ''
    text = rows[row][0]
    _say(text, interrupt=interrupt)
    return text


def here():
    """``(text, rectangle)`` for the word the cursor is on, or the line.

    The WORD when the user has moved along the line, the whole line when
    they have not - because a click meant for a line of one word should not
    need a Right first, and a click meant for the third word of a sentence
    must not land on the first.
    """
    words = _words()
    with _LOCK:
        rows, row, at = _state['rows'], _state['row'], _state['word']
    if not 0 <= row < len(rows):
        return None
    if words and 0 < at < len(words):
        word = words[at]
        return word['text'], (word['left'], word['top'],
                              word['width'], word['height'])
    return rows[row]


def explore(x, y):
    """A finger at a point: the word drawn there, said. ``(ok, said)``.

    The line whose rectangle holds the point first, then the word on it
    under the finger; the line alone where the finger is between words.
    Said only when the finger has moved onto something else.
    """
    with _LOCK:
        rows = list(_state['rows'])
    found_row = None
    for index, (_text_, rect) in enumerate(rows):
        try:
            l, t, w, h = rect
        except Exception:                            # noqa: BLE001
            continue
        if l <= x < l + w and t <= y < t + h:
            found_row = index
            break
    if found_row is None:
        return False, ''
    found_word = 0
    for index, word in enumerate(_words(found_row)):
        try:
            if word['left'] <= x < word['left'] + word['width']:
                found_word = index
                break
        except Exception:                            # noqa: BLE001
            continue
    with _LOCK:
        same = (_state.get('explored') == (found_row, found_word)
                and _state['row'] == found_row
                and _state['word'] == found_word)
        if same:
            return True, ''
        _state['explored'] = (found_row, found_word)
        _state['row'] = found_row
        _state['word'] = found_word
        _state['moves'] += 1
    words = _words(found_row)
    if words and found_word > 0:
        _say(words[found_word]['text'])
        return True, words[found_word]['text']
    return True, say_line(beep=True)


def move_corner(dx_sign, dy_sign):
    """A corner of what was read - the numpad diagonals, as everywhere.

    The first or the last line, at its first or its last word, with the
    corner's name said first.
    """
    with _LOCK:
        rows = _state['rows']
        if not rows:
            return False, ''
        _state['row'] = len(rows) - 1 if dy_sign > 0 else 0
        _state['word'] = 0
        _state['moves'] += 1
    try:
        from . import virtualWindow
        name = virtualWindow.corner_name(dx_sign, dy_sign)
    except Exception:                                # noqa: BLE001
        name = ''
    words = _words()
    if dx_sign > 0 and words:
        with _LOCK:
            _state['word'] = len(words) - 1
        said = words[-1]['text']
    else:
        with _LOCK:
            row = _state['row']
        said = rows[row][0] if 0 <= row < len(rows) else ''
    _beep(_state['row'])
    _say((name + ', ' + said) if name else said)
    return True, said


def reviewing_cursor():
    with _LOCK:
        return _state['row'], _state['word']


def click():
    """Click where the cursor is. ``(ok, sentence)``.

    Not "activate the control": there is no control. There is a place on
    the screen where those words are drawn, and clicking it is what a
    sighted person would do - which is the whole reason the coordinates are
    kept.
    """
    found = here()
    if found is None:
        # Translators: said when there is nothing under the review cursor.
        return False, _('There is nothing here to click')
    text, rect = found
    from . import smart
    ok, said = smart._click(rect, text)
    if ok:
        with _LOCK:
            _state['clicks'] += 1
    return ok, said


def _beep(row):
    if compat.tones is None:
        return
    within = row % VISIBLE
    span = max(1, VISIBLE - 1)
    frequency = FREQ_TOP - (within / float(span)) * (FREQ_TOP - FREQ_BOTTOM)
    try:
        compat.tones.beep(int(frequency), BEEP_MS)
    except Exception:                                # noqa: BLE001
        pass


def _edge():
    try:
        from . import earcons
        earcons.play_named('edge.ogg')
    except Exception:                                # noqa: BLE001
        pass


def _say(text, interrupt=True):
    if compat.speech is None:
        return
    try:
        compat.speech.speakMessage(str(text))
    except Exception:                                # noqa: BLE001
        pass


def left_the_window():
    """Whether the review is up but the user has gone somewhere else."""
    if not reviewing():
        return False
    with _LOCK:
        hwnd = _state['hwnd']
    if _foreground() in (0, hwnd):
        return False
    stop()
    return True
