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
    """A new reading of a window. Keeps the cursor if it still makes sense.

    A game re-reads whenever the picture changes, and a cursor that jumped
    back to the top on every change would make the model unusable exactly
    when something is happening. So the control the user was on is looked
    for by name, and only a control that has really gone moves them.
    """
    controls = controls_in(reading)
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

    Through Titan, which knows where the thing it read actually is. There
    is no arithmetic here and no coordinate: a control is pressed by the
    name it was read under, which is the only identifier that survives the
    screen being read again.
    """
    found = here()
    if not found:
        return False, _('There is nothing to press.')
    from .link import LINK
    if not LINK.connected():
        return False, _('Titan is not running.')
    name = found['control']['name']
    ok, said = LINK.run_action('ocr', 'press', name=name)
    if not ok:
        return False, str(said or '')
    return True, str(said or '')


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
