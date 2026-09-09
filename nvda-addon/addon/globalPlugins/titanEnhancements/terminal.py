# -*- coding: utf-8 -*-
"""A terminal, reviewed the way Titan Access reviews one.

Ported from `data/components/titan access/titan_access/app_modules/
terminal.py`, and the reason for porting rather than pointing at NVDA's own
review cursor is the INTERACTION. NVDA can review a console perfectly well,
with the reader key and the numpad; Titan Access gives a terminal something
else, and it is what people who live in a shell actually use:

* **Numpad minus turns review on**, and then the **plain arrow keys** walk
  the buffer - no modifier, nothing held. Up and Down are lines, Left and
  Right are characters, Page Up and Page Down are a screenful, Home and End
  are the ends of the line. Escape, or numpad minus again, leaves.
* **Every line movement plays a short beep pitched by where the line is on
  the screen** - top of the screenful high, bottom low. It is the thing an
  audio game does, and in a wall of build output it is the difference
  between knowing roughly where you are and counting lines.

Three rules taken from Titan Access along with the behaviour:

* **The keys are borrowed, never stolen.** The arrows are bound only while
  review is really on, in a terminal, and given straight back. A reader that
  held the arrow keys would break every shell it was not in.
* **Ctrl and Alt are the application's.** A combination is a shell shortcut
  and is never ours, whatever review is doing.
* **The buffer is read through NVDA, not through UI Automation of our
  own.** NVDA already knows how to get the text out of conhost, Windows
  Terminal, PuTTY and mintty - it is a `TextInfo` away - and a second
  implementation would be a second thing to be wrong about a console host
  nobody here has.
"""

import threading

from . import compat
from . import i18n

_ = i18n.install(globals())

#: Every terminal-ish program this serves. Titan Access's own list, by the
#: executable, because a window class is not enough: Windows Terminal, an
#: old conhost and PuTTY share nothing between them.
PROGRAMS = frozenset({
    'cmd', 'powershell', 'pwsh', 'conhost', 'openconsole',
    'windowsterminal', 'wt', 'windowsterminalpreview',
    'putty', 'kitty', 'mintty', 'bash', 'wsl', 'wslhost',
    'cmder', 'conemu', 'conemu64', 'alacritty', 'hyper',
})

#: And the window classes, for a host started under another name.
CLASSES = frozenset({
    'ConsoleWindowClass', 'CASCADIA_HOSTING_WINDOW_CLASS',
    'PuTTY', 'mintty', 'VirtualConsoleClass',
})

#: The beep that says where the line is. Titan Access's own band: high at
#: the top of the screenful, low at the bottom, and short enough never to
#: mask the line being spoken after it.
FREQ_TOP = 1650
FREQ_BOTTOM = 420
BEEP_MS = 22

#: How tall a screenful is taken to be when the host will not say. Page Up
#: and Page Down step exactly this, so the beep's pattern repeats and "where
#: am I on the screen" stays the same question through the scrollback.
VISIBLE = 25

_LOCK = threading.RLock()
_state = {'on': False, 'row': 0, 'col': 0, 'lines': [], 'window': 0,
          'moves': 0}


def report():
    with _LOCK:
        return {'reviewing': _state['on'], 'row': _state['row'],
                'lines': len(_state['lines']), 'moves': _state['moves']}


def reviewing():
    with _LOCK:
        return bool(_state['on'])


# --------------------------------------------------------------------------- #
# Is this a terminal
# --------------------------------------------------------------------------- #
def _text(value):
    return str(value or '').strip()


def is_terminal(obj=None):
    """Whether the thing in front is a terminal. Never raises."""
    if obj is None:
        try:
            import api
            obj = api.getFocusObject()
        except Exception:                            # noqa: BLE001
            return False
    if obj is None:
        return False
    if _text(getattr(obj, 'windowClassName', '')) in CLASSES:
        return True
    try:
        from . import perProgram
        program = _text(perProgram.application_of(obj)).lower()
    except Exception:                                # noqa: BLE001
        program = ''
    if program.endswith('.exe'):
        program = program[:-4]
    return program in PROGRAMS


# --------------------------------------------------------------------------- #
# The buffer
# --------------------------------------------------------------------------- #
def _read_lines(obj=None):
    """Everything the terminal is showing, as lines. ``[]`` when it cannot
    be read, which is not an error: a host with no text interface simply
    never enters review."""
    if obj is None:
        try:
            import api
            obj = api.getFocusObject()
        except Exception:                            # noqa: BLE001
            return []
    try:
        import textInfos
        info = obj.makeTextInfo(textInfos.POSITION_ALL)
    except Exception:                                # noqa: BLE001
        return []
    try:
        return str(info.text or '').splitlines()
    except Exception:                                # noqa: BLE001
        return []


def _refresh(obj=None):
    lines = _read_lines(obj)
    with _LOCK:
        _state['lines'] = lines
    return lines


def _last_written(lines):
    """The bottom-most line with anything on it - where the prompt is.

    Entering review at the very bottom of a buffer padded with blank lines
    would put the cursor below everything that has been said, which reads as
    a terminal with nothing in it.
    """
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].strip():
            return index
    return max(0, len(lines) - 1)


# --------------------------------------------------------------------------- #
# Turning it on and off
# --------------------------------------------------------------------------- #
def toggle():
    """Numpad minus. ``(on, sentence)``."""
    if reviewing():
        return stop()
    return start()


def start(obj=None):
    if not is_terminal(obj):
        # Translators: said when terminal review is asked for elsewhere.
        return False, _('This is not a terminal.')
    lines = _refresh(obj)
    if not lines:
        # Translators: said when a terminal will not give up its text.
        return False, _('This terminal will not say what is in it.')
    # **Only once it has really started.** Ending the other reviews
    # from the top of this would end them for a terminal that then
    # refused - so the user would lose the review they were in and
    # gain nothing.
    from . import reviews
    reviews.stop_others('terminal')
    with _LOCK:
        _state['on'] = True
        _state['row'] = _last_written(lines)
        _state['col'] = 0
        try:
            import api
            _state['window'] = int(getattr(api.getFocusObject(),
                                           'windowHandle', 0) or 0)
        except Exception:                            # noqa: BLE001
            _state['window'] = 0
    _cue(True)
    say_line(beep=True, interrupt=False)
    # Translators: said when terminal review starts. Terse and
    # symmetrical with the line below it on purpose: this is a state
    # toggle a user hears many times a day, and a sentence about it is
    # a sentence they learn to talk over.
    return True, _('Terminal review on')


def stop():
    was = reviewing()
    with _LOCK:
        _state['on'] = False
        _state['lines'] = []
    if was:
        _cue(False)
    # Translators: said when terminal review ends.
    return False, _('Terminal review off')


def _cue(on):
    """Titan's own "a mode has started / ended" sounds, which is what Titan
    Access plays here and what the user already knows them as."""
    try:
        from . import earcons
        earcons.play_named('keyon.ogg' if on else 'keyoff.ogg')
    except Exception:                                # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# Moving
# --------------------------------------------------------------------------- #
def _lines_now():
    with _LOCK:
        return list(_state['lines'])


def move_line(delta):
    lines = _refresh()
    if not lines:
        return False
    with _LOCK:
        row = _state['row'] + delta
        if row < 0 or row >= len(lines):
            _state['row'] = max(0, min(row, len(lines) - 1))
            edge = True
        else:
            _state['row'] = row
            edge = False
        _state['col'] = 0
        _state['moves'] += 1
    if edge:
        _edge()
    say_line(beep=True)
    return True


def move_page(direction):
    return move_line(direction * VISIBLE)


def move_char(delta):
    lines = _lines_now()
    with _LOCK:
        row = _state['row']
        line = lines[row] if 0 <= row < len(lines) else ''
        col = _state['col'] + delta
        if col < 0 or col >= len(line):
            edge = True
            col = max(0, min(col, max(0, len(line) - 1)))
        else:
            edge = False
        _state['col'] = col
        _state['moves'] += 1
    if edge:
        _edge()
    if line:
        _say(line[col] if col < len(line) else '', spell=True)
    return True


def move_end(to_end):
    lines = _lines_now()
    with _LOCK:
        row = _state['row']
        line = lines[row] if 0 <= row < len(lines) else ''
        _state['col'] = max(0, len(line) - 1) if to_end else 0
        col = _state['col']
        _state['moves'] += 1
    if line:
        _say(line[col] if col < len(line) else '', spell=True)
    return True


def say_line(beep=False, interrupt=True):
    lines = _lines_now()
    with _LOCK:
        row = _state['row']
    if beep:
        _beep(row)
    line = lines[row] if 0 <= row < len(lines) else ''
    if line.strip():
        _say(line, interrupt=interrupt)
    else:
        # Translators: said for an empty line in a terminal.
        _say(_('blank'), interrupt=interrupt)
    return line


def _beep(row):
    """Pitched by where the line is on ITS screenful.

    Page Up and Page Down move exactly one screenful, so the pattern repeats
    and the pitch means the same thing all the way through the scrollback -
    which is what makes it worth listening to rather than a noise per line.
    """
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


def _say(text, interrupt=True, spell=False):
    if compat.speech is None:
        return
    try:
        if spell and text:
            compat.speech.speakSpelling(text)
            return
        compat.speech.speakMessage(str(text))
    except Exception:                                # noqa: BLE001
        pass


def left_the_terminal():
    """Whether review is on but the user has gone somewhere else.

    Asked on every focus change. A review cursor left running over a window
    the user is no longer in would swallow their arrow keys in whatever they
    moved to, which is the one way this feature could make a machine worse.
    """
    if not reviewing():
        return False
    if is_terminal():
        return False
    stop()
    return True
