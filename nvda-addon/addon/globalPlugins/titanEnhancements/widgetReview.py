# -*- coding: utf-8 -*-
"""A Titan widget, walked with the arrow keys.

The fifth thing walked the same way, and the one whose cursor is not ours.
A widget - the taskbar, the quick settings, the system desktop - is a
control inside TITAN's own window, and Titan already knows how to move
through one: `widgets.move` with `up`, `down`, `left` or `right`,
`widgets.read` for what is under its cursor now, `widgets.press` to
activate it. So this is a review whose cursor lives in another process:
the arrows ask Titan to move and say whatever came back.

**Which is why it holds no list.** The other reviews build the whole thing
up front - a terminal's lines, a recognised screen, an application's
controls, a window's tree - and can then move about locally. A widget
answers one element at a time and nothing answers how many there are, so
there is no list to build and no "3 of 10" to say. Pretending otherwise
would mean counting by walking the widget from end to end, which changes
the very cursor the user is sitting on.

**An edge is heard rather than announced.** Titan answers the same element
when a move went nowhere, so a move that changed nothing is the end of the
widget - said with the reviews' own edge tone, exactly as walking off the
end of a list is said everywhere else here.
"""

import threading

from . import compat
from . import i18n
from . import icons
from . import titan

_ = i18n.install(globals())

_LOCK = threading.RLock()
_state = {'on': False, 'widget': '', 'name': '', 'said': '', 'moves': 0,
          'presses': 0}


def report():
    with _LOCK:
        return dict(_state)


def reviewing():
    with _LOCK:
        return bool(_state['on'])


def widget():
    with _LOCK:
        return str(_state['widget'])


def start(name, label=''):
    """Walk a widget. ``(ok, sentence)`` - the read happens on a worker."""
    from . import reviews
    reviews.stop_others('widgetReview')
    with _LOCK:
        _state.update({'on': True, 'widget': str(name),
                       'name': str(label or name), 'said': ''})

    def work():
        ok, said = titan.read_widget(name)
        if not ok:
            stop()
            _say(str(said))
            return
        with _LOCK:
            _state['said'] = str(said)
        if not icons.play('open-object'):
            _cue(True)
        say_here()
    threading.Thread(target=work, name='TitanWidgetReview',
                     daemon=True).start()
    # Symmetrical with `stop`, for the same reason: which widget it is
    # gets said by the first element, immediately after.
    # Translators: said when a widget starts being walked.
    return True, _('Widget review on')


def stop():
    with _LOCK:
        was = _state['on']
        _state.update({'on': False, 'widget': '', 'said': ''})
    if was and not icons.play('close-object'):
        _cue(False)
    # Translators: said when a widget stops being walked.
    return False, _('Widget review off')


def move(direction):
    """Ask Titan to move inside the widget, and say what is there now."""
    if not reviewing():
        return False, ''
    name = widget()
    with _LOCK:
        before = _state['said']
        _state['moves'] += 1

    def work():
        ok, said = titan.move_widget(name, direction)
        if not ok:
            _say(str(said))
            return
        with _LOCK:
            _state['said'] = str(said)
        if str(said) == before:
            # Titan answers the same element when the move went nowhere,
            # so this is the end of the widget. Said as an edge, which is
            # how the end of anything is said in this add-on.
            _edge()
            return
        say_here()
    threading.Thread(target=work, name='TitanWidgetMove',
                     daemon=True).start()
    return True, ''


def press():
    if not reviewing():
        return False, ''
    name = widget()
    with _LOCK:
        _state['presses'] += 1
    icons.play('button')

    def work():
        ok, said = titan.press_widget(name)
        if said:
            _say(str(said))
        elif not ok:
            icons.play('warn-user')
        # What the widget shows may have changed by being pressed.
        ok, now = titan.read_widget(name)
        if ok:
            with _LOCK:
                _state['said'] = str(now)
            say_here(beep=False)
    threading.Thread(target=work, name='TitanWidgetPress',
                     daemon=True).start()
    return True, ''


def say_here(beep=True):
    with _LOCK:
        said = _state['said']
        name = _state['name']
    if not said:
        # Translators: said when a widget has nothing under its cursor.
        return False, _('Nothing here')
    if beep:
        icons.play('item')
    _say_parts([(said, 'name'), (name, 'place')])
    return True, said


def _say_parts(parts):
    if not parts:
        return
    from . import elements
    sequence = elements.sequence(parts)
    if not sequence or compat.speech is None:
        _say(', '.join(str(text) for text, _voice in parts))
        return
    try:
        from . import voices
        voices.speak_sequence(sequence)
    except Exception:                                # noqa: BLE001
        _say(', '.join(str(text) for text, _voice in parts))


def _edge():
    if compat.tones is None:
        return
    try:
        compat.tones.beep(220, 30)
    except Exception:                                # noqa: BLE001
        pass


def _cue(on):
    if compat.tones is None:
        return
    try:
        compat.tones.beep(660 if on else 440, 40)
    except Exception:                                # noqa: BLE001
        pass


def _say(text):
    if compat.speech is None:
        return
    try:
        compat.speech.speakMessage(str(text))
    except Exception:                                # noqa: BLE001
        pass
