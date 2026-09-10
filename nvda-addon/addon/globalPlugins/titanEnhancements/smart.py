# -*- coding: utf-8 -*-
"""A drawn window, made navigable: Tab and the arrows, as on a real one.

Reading a window aloud is where this started and it is not enough. A
reading you cannot move through is a wall of text: the user hears
everything, in the order the model happened to write it, and can act on
none of it. What makes a window usable is that the keyboard walks it - Tab
to the next control, the arrows through a list, Enter to press what you are
on - and that is exactly what a drawn window takes away.

So the reading becomes a **model of controls**, and the keys that would
have moved through real ones move through these instead. The user tabs
round a Unity game's menu the way they tab round a dialog: a name, what it
is, and Enter presses it.

Three things make it honest rather than a pretence:

* **What is pressed is the thing that was read.** Titan's AI OCR already
  knows where each control it read is on the screen, and `ocr.press` clicks
  it by name. Nothing here invents a coordinate.
* **The keys are borrowed, never stolen.** They are bound only while the
  drawn window really has the focus, they are given back the moment it does
  not, and any key this does not use is passed straight through with
  `gesture.send()`. A reader that swallowed Tab everywhere would be worse
  than one that never read the game at all.
* **What was read is said to be a reading.** These controls are what a
  model saw in a picture, not what a program declared, and they are spoken
  in the voice class that says so - the same one an AI-derived label uses.

The reading itself comes from :mod:`surface`, which watches the window and
re-reads it when the picture changes; a new reading replaces the model and
keeps the cursor where it was if that control is still there.
"""

import threading

from . import compat
from . import i18n

_ = i18n.install(globals())

#: A reading is prose written for a person, and its shape is
#: `model.elements_as_lines`: a title, a summary, then `[Region]` headings
#: with each element indented under them. The indented lines are the
#: controls; everything else is furniture.
INDENT = '  '

#: Titan's own sounds for a virtual cursor appearing and going away. They
#: are the ones Titan Access has always played for exactly this - a screen
#: that is not the real one being put up and taken down - and they live in
#: the theme (`sfx/<theme>/SRE/`), so a user with no Titan Access still
#: has them and a theme can replace them.
SOUND_ON = 'vscreenOn.ogg'
SOUND_OFF = 'vscreenOff.ogg'

#: What a control's line is made of - `Element.spoken()` joins them with
#: commas: the name, the value, the role and the state.
_ROLES_THAT_ACT = ('button', 'link', 'checkbox', 'radio', 'tab', 'menuitem',
                   'combobox', 'textbox', 'field', 'slider')

_LOCK = threading.RLock()
_state = {'hwnd': 0, 'controls': [], 'at': -1, 'region': '', 'reading': ''}


def report():
    with _LOCK:
        return {'window': _state['hwnd'], 'controls': len(_state['controls']),
                'at': _state['at']}


def forget():
    with _LOCK:
        had = bool(_state['controls'])
        _state.update({'hwnd': 0, 'controls': [], 'at': -1, 'region': '',
                       'reading': ''})
    if had:
        _announce(False)


def active():
    with _LOCK:
        return bool(_state['hwnd'] and _state['controls'])


def window():
    with _LOCK:
        return int(_state['hwnd'] or 0)


# --------------------------------------------------------------------------- #
# The reading, as controls
# --------------------------------------------------------------------------- #
def controls_in(reading):
    """``[{'name', 'said', 'region'}]`` out of a reading. ``[]`` for none.

    The indented lines, in the order the model wrote them, which is the
    order they appear on the screen - so Tab goes down the menu rather than
    round it in some order of its own.
    """
    found = []
    region = ''
    for line in str(reading or '').splitlines():
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            region = stripped[1:-1].strip()
            continue
        if not line.startswith(INDENT):
            continue                                 # the title, the summary
        name = stripped.split(',')[0].strip()
        if not name or name == '(empty)':
            continue
        found.append({'name': name, 'said': stripped, 'region': region})
    return found


def controls_from(reading):
    """The same, out of a LOCAL reading (:mod:`localOcr`).

    **The cheap tier is a first-class one.** Windows' own OCR gives the
    words and a rectangle per line, in real screen coordinates - which is
    everything a cursor needs. So a drawn window becomes navigable with no
    model asked, nothing sent anywhere and nothing spent, and the AI is left
    for the question only it can answer: which of these is a button, and
    what is highlighted.

    A control from here carries its ``rect``, so pressing it is a click at a
    place we were told rather than a name handed back to Titan.
    """
    if reading is None:
        return []
    # **Every PIECE, not every line.** This walked `reading.rows()`, which
    # is a whole line of the picture - so a menu bar read as
    # "File Edit View" was one control the cursor could not get inside,
    # and a row of a list with a name and a size beside it was one lump of
    # text. `virtualInput` already splits a row where the gaps are and
    # already knows which pieces sit in a highlighted area; using it is
    # what makes this tier show what is really there rather than the
    # lines it came in.
    from . import virtualInput
    try:
        nodes = virtualInput.build(reading,
                                   getattr(reading, 'highlights', None))
    except Exception:                                # noqa: BLE001
        nodes = []
    # **And what the window IS, not only what is in it.** The scene says
    # which row is the menu bar, which is the status line, where the
    # columns are and what has been highlighted - all from the geometry,
    # so it costs nothing and works in every language.
    from . import sceneModel
    try:
        found_scene = sceneModel.scene(nodes)
    except Exception:                                # noqa: BLE001
        found_scene = {'rows': []}
    found = []
    for row in found_scene.get('rows') or []:
        for piece in row.get('cells') or []:
            name = str(piece.get('text') or '').strip()
            if not name:
                continue
            kind = sceneModel.said_kind(piece.get('kind'))
            found.append({'name': name, 'said': name,
                          # What it IS, as far as a picture can say: a
                          # menu, a status line, a cell of a row, or the
                          # piece the window has highlighted - which in a
                          # game's menu and a guest's file list is the
                          # whole interface.
                          'region': kind,
                          'selected': bool(piece.get('selected')),
                          'kind': str(piece.get('kind') or 'text'),
                          'line': int(piece.get('line', 0) or 0),
                          'column': int(piece.get('column', 0) or 0),
                          'rect': (piece['left'], piece['top'],
                                   piece['width'], piece['height'])})
    if not found:
        # A reading with no pieces in it is still a reading: fall back to
        # the lines rather than answering that the window is empty.
        for text, rect in reading.rows():
            name = str(text or '').strip()
            if name:
                found.append({'name': name, 'said': name, 'region': '',
                              'selected': False, 'rect': tuple(rect)})
    return found


def selected_in(controls):
    """The controls the picture has highlighted, in order."""
    return [one for one in (controls or []) if one.get('selected')]


def take_local(hwnd, reading):
    """A new LOCAL reading of a window. Same cursor rules as `take`."""
    return _take(hwnd, controls_from(reading),
                 reading.text if reading else '')


def _announce(entered):
    """Say that the cursor has appeared, or gone. Sound first, then words.

    **This is a mode change, and a mode change has to be announced.** The
    keyboard is about to mean something different - Tab walks a model of
    what a picture was read as, rather than doing whatever the program
    does with it - and a user who is not told that is a user pressing Tab
    and hearing something they cannot account for.
    """
    from . import compat
    try:
        from . import earcons
        earcons.play_named(SOUND_ON if entered else SOUND_OFF)
    except Exception:                                # noqa: BLE001
        pass
    if compat.ui is None or compat.queueHandler is None:
        return False
    said = (
        # Translators: said when an unreadable window has been read as a
        # picture and its controls can now be walked with Tab and the
        # arrows.
        _('Window recognised, Native TCE cursor') if entered else
        # Translators: said when that stops.
        _('Native TCE cursor off'))

    def speak():
        try:
            compat.ui.message(said)
        except Exception:                            # noqa: BLE001
            pass
    compat.queueHandler.queueFunction(compat.queueHandler.eventQueue, speak)
    return True


def take(hwnd, reading):
    """A new reading of a window. Keeps the cursor if it still makes sense."""
    return _take(hwnd, controls_in(reading), str(reading or ''))


def _take(hwnd, controls, reading):
    """One reading, whichever tier it came from.

    A game re-reads whenever the picture changes, and a cursor that jumped
    back to the top on every change would make the model unusable exactly
    when something is happening. So the control the user was on is looked
    for by name, and only a control that has really gone moves them.
    """
    with _LOCK:
        arrived = bool(controls) and not (_state['controls']
                                          and _state['hwnd'] == int(hwnd or 0))
        was = ''
        if 0 <= _state['at'] < len(_state['controls']):
            was = _state['controls'][_state['at']]['name']
        _state['hwnd'] = int(hwnd or 0)
        _state['controls'] = controls
        _state['reading'] = str(reading or '')
        _state['at'] = -1
        if was:
            for index, control in enumerate(controls):
                if control['name'] == was:
                    _state['at'] = index
                    break
    if arrived:
        # Once, on arriving - not on every re-read, which happens whenever
        # the picture changes and would be a sound and a sentence over the
        # top of whatever the user is doing.
        _announce(True)
    return len(controls)


# --------------------------------------------------------------------------- #
# Moving through them
# --------------------------------------------------------------------------- #
def move(step):
    """Next or previous control. ``None`` when there is nothing to move to."""
    with _LOCK:
        controls = list(_state['controls'])
        at = _state['at']
        if not controls:
            return None
        if at < 0:
            at = 0 if step > 0 else len(controls) - 1
        else:
            at += step
            if at < 0 or at >= len(controls):
                # **It stops at the ends rather than wrapping.** A wall is
                # information: a user who tabs to the bottom of a menu and
                # is put back at the top cannot tell how long it is.
                at = 0 if at < 0 else len(controls) - 1
                _state['at'] = at
                return {'control': controls[at], 'at': at,
                        'count': len(controls), 'edge': True}
        _state['at'] = at
        return {'control': controls[at], 'at': at, 'count': len(controls),
                'edge': False}


def here():
    with _LOCK:
        if 0 <= _state['at'] < len(_state['controls']):
            return {'control': _state['controls'][_state['at']],
                    'at': _state['at'], 'count': len(_state['controls']),
                    'edge': False}
    return None


def say(moved):
    """Announce a control the way a reader announces one.

    The name, then what it is, then where it is in the window - and all of
    it in the voice class for something a model READ rather than something
    a program declared, because the difference matters and the user cannot
    see it.
    """
    if not moved:
        return False
    control = moved['control']
    from . import elements
    from . import voices
    parts = [(control['name'], 'guessed')]
    rest = control['said'][len(control['name']):].strip(' ,')
    if rest:
        parts.append((rest, 'kind'))
    if control.get('region'):
        parts.append((control['region'], 'context'))
    parts.append((_('{index} of {count}').format(index=moved['at'] + 1,
                                                 count=moved['count']),
                  'place'))
    speech = compat.speech
    if speech is None:
        return False
    sequence = voices.sequence(parts)
    if not sequence:
        return False
    try:
        speech.cancelSpeech()
    except Exception:                                # noqa: BLE001
        pass
    try:
        speech.speak(sequence)
        return True
    except Exception:                                # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Pressing one
# --------------------------------------------------------------------------- #
def press():
    """Press the control the cursor is on. ``(ok, sentence)``.

    **A control that knows where it is presses itself.** A local reading
    (Windows' own OCR) carries a real screen rectangle per line, so pressing
    is a click at a place we were told - no model, no request, nothing sent
    anywhere, and it works with Titan closed.

    Everything else goes through Titan, which knows where the thing IT read
    actually is: there is no arithmetic here and no invented coordinate, and
    a control is pressed by the name it was read under, which is the only
    identifier that survives the screen being read again.
    """
    found = here()
    if not found:
        return False, _('There is nothing to press.')
    control = found['control']
    rect = control.get('rect')
    if rect:
        return _click(rect, control['name'])
    from .link import LINK
    if not LINK.connected():
        return False, _('Titan is not running.')
    ok, said = LINK.run_action('ocr', 'press', name=control['name'])
    if not ok:
        return False, str(said or '')
    return True, str(said or '')


#: Windows' own mouse events. `SendInput` would be the modern way and is
#: worse here: it is refused by a window running as administrator when NVDA
#: is not, and `mouse_event` is what NVDA's own mouse handling uses.
_MOUSE_LEFT_DOWN = 0x0002
_MOUSE_LEFT_UP = 0x0004


def _click(rect, name):
    """Click the middle of a rectangle, and put the mouse back.

    Putting it back is not politeness: a mouse left sitting over another
    control leaves that control hovered, which changes what some programs
    show and what the next reading says about them.
    """
    try:
        import ctypes
        from ctypes import wintypes
    except Exception as error:                       # noqa: BLE001
        return False, str(error)
    left, top, width, height = rect
    if width <= 0 or height <= 0:
        return False, _('That control has no place on the screen.')
    user32 = ctypes.windll.user32
    was = wintypes.POINT()
    try:
        user32.GetCursorPos(ctypes.byref(was))
    except Exception:                                # noqa: BLE001
        was = None
    try:
        user32.SetCursorPos(int(left + width // 2), int(top + height // 2))
        user32.mouse_event(_MOUSE_LEFT_DOWN, 0, 0, 0, 0)
        user32.mouse_event(_MOUSE_LEFT_UP, 0, 0, 0, 0)
    except Exception as error:                       # noqa: BLE001
        return False, str(error)
    finally:
        if was is not None:
            try:
                user32.SetCursorPos(was.x, was.y)
            except Exception:                        # noqa: BLE001
                pass
    # Translators: said when a control read from the screen is pressed.
    return True, _('Pressed {name}.').format(name=name)
def send_key(key):
    """Send a whole key to the window, which is what a game usually wants.

    A drawn window often has no controls to press at all - it has a menu
    that answers the arrow keys. Titan's AI OCR can send a key to the
    window it read, and that is a different thing from pressing a control:
    it is what makes a game playable rather than merely readable.
    """
    from .link import LINK
    if not LINK.connected():
        return False, _('Titan is not running.')
    ok, said = LINK.run_action('ocr', 'send_key', key=key)
    return bool(ok), str(said or '')
