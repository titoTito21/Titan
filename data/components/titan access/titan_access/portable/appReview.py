# -*- coding: utf-8 -*-
"""A Titan application as a virtual window, walked with the arrow keys.

The same idea as the terminal review (:mod:`terminal`) and the recognised
screen (:mod:`ocrReview`), applied to something better than a picture:
Titan can describe one of its own applications as a flat list of controls
with a kind, a label and a value (`src/app_ui`), so what the arrows walk
here is not text that was read off the screen - it is the interface
itself, and Enter presses the real control.

**Why a review rather than only a window.** :mod:`appScreen` builds the
same screen as real wx controls, and that is worth having: a real check box
is announced by Windows as a check box. But it is a WINDOW - one more thing
in Alt+Tab, one more place for the keyboard to be - and the user asked for
the shape this add-on already has: no window at all, the same keys as the
two reviews, working from wherever you are. Titan's own AI OCR made exactly
this pair of choices for the same reason (`mimic.py` reads, `form_view.py`
rebuilds), so this is the reader's half of a decision the desktop already
made.

* **Up and Down are controls, Left and Right are what is INSIDE one** - the
  rows of a list, the options of a choice. That is the same shape as the
  OCR review's lines and words, in the same places, because a user should
  learn one set of keys and not three.
* **Home and End** are the first and last control, **Page Up and Page
  Down** move by ten.
* **Enter presses**: a button is pressed, a check box is toggled, a row of
  a list is opened. **Space** toggles what can be toggled.
* **F5 reads the screen again**, **Escape leaves the review** - and
  deliberately does not close the application, because a key that both
  leaves and quits is a key nobody can use safely.
* **Each control is marked by a short beep pitched by where it is** in the
  screen, first high and last low - the reviews' own band, so all three
  sound like one feature.

**Nothing waits on NVDA's main thread.** Moving is local, because the
screen is already in hand; pressing is a round trip to another process and
happens on a worker, announced when it comes back. A reader that waited on
a pipe would be a reader that had stopped answering.

**What it says is said in the user's own voice classes** - the label as a
name, what the control IS a little lower, its value a little higher - so a
described application is read exactly like anything else this add-on reads,
rather than in a voice of its own.
"""

import threading

from . import compat
from . import i18n
from . import icons
from . import titan

_ = i18n.install(globals())

#: The beep that says where in the screen the control is. The reviews' own
#: band, deliberately.
FREQ_TOP = 1650
FREQ_BOTTOM = 420
BEEP_MS = 22

#: How far a page key moves, and what the beep's pitch is measured against
#: when a screen is smaller than this.
PAGE = 10

#: Kinds that hold rows or options - the things Left and Right walk.
INNER = ('list', 'table', 'tree', 'choice', 'tabs')

#: Kinds Enter and Space act on directly.
PRESSABLE = ('button',)
TOGGLEABLE = ('check',)

_LOCK = threading.RLock()
_state = {'on': False, 'session': '', 'name': '', 'screen': {},
          'at': 0, 'inner': 0, 'moves': 0, 'presses': 0, 'why': ''}


def report():
    with _LOCK:
        return {'reviewing': _state['on'], 'application': _state['name'],
                'at': _state['at'], 'inner': _state['inner'],
                'controls': len(_controls()), 'moves': _state['moves'],
                'presses': _state['presses'], 'why': _state['why']}


def reviewing():
    with _LOCK:
        return bool(_state['on'])


def session():
    with _LOCK:
        return str(_state['session'])


def _controls(screen=None):
    """The controls of the screen in hand, in the order they were given.

    A screen's order IS its reading order - the shim keeps what the
    application's own sizers were given, because a sizer's order is the
    only part of a layout that means anything to somebody who cannot see
    the window.
    """
    if screen is None:
        screen = _state.get('screen') or {}
    rows = screen.get('controls') if isinstance(screen, dict) else None
    return [row for row in (rows or []) if isinstance(row, dict)]


# --------------------------------------------------------------------------- #
# Opening and leaving
# --------------------------------------------------------------------------- #
def start(name, then=None):
    """Open an application and review it. Answers ``(ok, sentence)``.

    The open is a subprocess start at Titan's end, so it happens on a
    worker and this answers at once with what is being done.
    """
    if reviewing():
        stop()
    from . import reviews
    reviews.stop_others('appReview')

    def work():
        ok, data = titan.open_described(name)
        if not ok:
            _say(str(data))
            if then is not None:
                then(False, str(data))
            return
        token = str((data or {}).get('session') or '')
        if not token:
            # Translators: said when Titan would not open an application.
            _say(_('Titan did not open that application.'))
            if then is not None:
                then(False, '')
            return
        with _LOCK:
            _state.update({'on': True, 'session': token, 'at': 0, 'inner': 0,
                           'name': str(data.get('application') or name),
                           'screen': data.get('screen') or {}, 'why': ''})
        said = str(data.get('said') or '')
        if data.get('mirror'):
            # A mirror is what Windows can see of the window, which is a
            # weaker thing than the application's own account of itself,
            # and presenting the two as the same would be dishonest.
            said = (said + ' ' if said else '') + _(
                'read off the window, so it says less')
        if said:
            _say(said)
        if not icons.play('open-object'):
            _cue(True)
        say_here()
        if then is not None:
            then(True, '')
    threading.Thread(target=work, name='TitanAppReview',
                     daemon=True).start()
    # Translators: said while a Titan application is being opened.
    return True, _('Opening {what}').format(what=name)


def stop(close=False):
    """Leave the review. ``close`` also closes the application."""
    with _LOCK:
        was = _state['on']
        token = _state['session']
        _state.update({'on': False, 'session': '', 'screen': {}, 'at': 0,
                       'inner': 0})
    if was and not icons.play('close-object'):
        _cue(False)
    if close and token:
        threading.Thread(
            target=lambda: titan.close_described(token),
            name='TitanAppClose', daemon=True).start()
        # Translators: said when a reviewed application is closed.
        return False, _('Application closed')
    # Translators: said when the review of an application is turned off.
    return False, _('Application review off')


def close_application():
    if not reviewing():
        # Translators: said when there is no application being reviewed.
        return False, _('No application is being reviewed')
    return stop(close=True)


def refresh():
    """Read the screen again. The application may have moved on its own."""
    if not reviewing():
        return False, _('No application is being reviewed')
    token = session()

    def work():
        ok, data = titan.described_screen(token)
        if not ok:
            _say(str(data))
            return
        _took(data)
        say_here()
    threading.Thread(target=work, name='TitanAppRefresh',
                     daemon=True).start()
    # Translators: said while the screen is read again.
    return True, _('Reading it again')


def _took(answer):
    """Keep a screen that came back, and say anything the application said.

    The cursor is kept where it was rather than reset: an application
    re-reads itself constantly, and a cursor that jumped to the top each
    time would be unusable exactly when something is happening.
    """
    if not isinstance(answer, dict):
        return
    said = str(answer.get('said') or '')
    screen = answer.get('screen')
    if said:
        # News first. The screen behind a save usually looks exactly as it
        # did before, so somebody handed only the screen is told nothing
        # at all about what happened.
        _say(said)
    if not isinstance(screen, dict):
        return
    with _LOCK:
        count = len(_controls(screen))
        _state['screen'] = screen
        if _state['at'] >= count:
            _state['at'] = max(0, count - 1)
        _state['inner'] = 0


# --------------------------------------------------------------------------- #
# Moving
# --------------------------------------------------------------------------- #
def move(delta):
    with _LOCK:
        controls = _controls()
        if not controls:
            return _nothing()
        at = _state['at'] + delta
        if at < 0 or at >= len(controls):
            _state['at'] = max(0, min(_state['at'], len(controls) - 1))
            _edge()
            return say_here(beep=False)
        _state['at'] = at
        _state['inner'] = _where_inside(controls[at])
        _state['moves'] += 1
    return say_here(beep=True)


def move_page(direction):
    return move(PAGE * (1 if direction > 0 else -1))


def move_end(to_end):
    with _LOCK:
        controls = _controls()
        if not controls:
            return _nothing()
        _state['at'] = len(controls) - 1 if to_end else 0
        _state['inner'] = _where_inside(controls[_state['at']])
        _state['moves'] += 1
    return say_here(beep=True)


def move_inside(delta):
    """Left and Right: the rows of a list, the options of a choice.

    A control with nothing inside it says its own value instead, which is
    what a user pressing Right on a field wants to hear - not silence, and
    not the next control, which is what Up and Down are for.
    """
    control = here()
    if control is None:
        return _nothing()
    rows = _inside(control)
    if not rows:
        return say_here(beep=False)
    with _LOCK:
        at = _state['inner'] + delta
        if at < 0 or at >= len(rows):
            _state['inner'] = max(0, min(_state['inner'], len(rows) - 1))
            _edge()
            return True, str(rows[_state['inner']])
        _state['inner'] = at
        _state['moves'] += 1
        said = str(rows[at])
    # Moving inside a list is a CHANGE to the application, not only to the
    # cursor: its own code reads which row is selected. It is sent, and the
    # answer is quiet - the row has already been spoken here.
    _send_inside(control, _state['inner'])
    _say_parts([(said, 'name'),
                (_('{at} of {count}').format(at=_state['inner'] + 1,
                                             count=len(rows)), 'place')])
    return True, said


def _where_inside(control):
    index = control.get('index')
    if isinstance(index, int) and index >= 0:
        return index
    return 0


def _inside(control):
    kind = str(control.get('kind') or '')
    if kind not in INNER:
        return []
    rows = control.get('items')
    if not rows:
        rows = control.get('options')
    return [row_text(row) for row in (rows or [])]


def _send_inside(control, index):
    kind = str(control.get('kind') or '')
    if kind not in INNER:
        return
    token = session()
    identifier = control.get('id')
    if not token or identifier is None:
        return
    threading.Thread(
        target=lambda: titan.set_described(token, identifier, index),
        name='TitanAppSet', daemon=True).start()


def here():
    with _LOCK:
        controls = _controls()
        at = _state['at']
        return controls[at] if 0 <= at < len(controls) else None


# --------------------------------------------------------------------------- #
# Acting
# --------------------------------------------------------------------------- #
def activate():
    """Enter: press a button, toggle a tick box, open a row."""
    control = here()
    if control is None:
        return _nothing()
    kind = str(control.get('kind') or '')
    token = session()
    identifier = control.get('id')
    if kind in PRESSABLE:
        icons.play('button')
        _act(lambda: titan.press_described(token, identifier))
        # Translators: said when a control is pressed.
        return True, _('Pressed')
    if kind in TOGGLEABLE:
        return toggle()
    if kind in ('list', 'table', 'tree'):
        # **Enter CLICKS the row**, which is what `app.press` on a list
        # really does: read out of the shim, a press on a `ListBox` fires
        # `EVT_LISTBOX_DCLICK`, on a `ListCtrl` `EVT_LIST_ITEM_ACTIVATED`
        # and on a tree `EVT_TREE_ITEM_ACTIVATED` - the application's own
        # "this row was opened", the same event a double click produces.
        #
        # Sending the KEY was what this did first, and it is weaker in the
        # way that matters: it does something only if the application
        # happens to bind Enter, and most of them bind the activation
        # instead. The key is kept as the fallback for the ones that do.
        icons.play('open-object')
        _act(lambda: _press_then_key(token, identifier))
        # Translators: said when a row of a list is opened.
        return True, _('Opened')
    if kind in ('text', 'multiline'):
        return type_here()
    _act(lambda: titan.key_described(token, 'enter'))
    return True, _('Opened')


def toggle():
    control = here()
    if control is None:
        return _nothing()
    if str(control.get('kind') or '') not in TOGGLEABLE:
        return activate()
    token = session()
    value = not bool(control.get('value'))
    icons.play('on' if value else 'off')
    _act(lambda: titan.set_described(token, control.get('id'), value))
    return True, _('Checked') if value else _('Unchecked')


def type_here(text=None):
    """Put something into the field the cursor is on.

    Asked for rather than typed into directly: a review is not a form, and
    a field that took every keystroke would take the arrow keys with them.
    """
    control = here()
    if control is None:
        return _nothing()
    if str(control.get('kind') or '') not in ('text', 'multiline'):
        # Translators: said when the cursor is not on something to type in.
        return False, _('This is not a field')
    if text is None:
        return True, ''
    token = session()
    _act(lambda: titan.set_described(token, control.get('id'), text))
    # Translators: said when something has been typed into a field.
    return True, _('Written')


def press_key(key):
    """One of the application's OWN keys - F1 to F5, Delete, and the rest."""
    if not reviewing():
        return _nothing()
    token = session()
    _act(lambda: titan.key_described(token, key))
    return True, ''


def _press_then_key(token, control):
    """Click the row; if nothing answered, send Enter instead.

    `answered` is the application saying whether anything of its own ran.
    A row that is clicked and handled is done; a row in an application
    that binds the key rather than the activation would otherwise be a
    press that silently did nothing, which is the failure this whole
    module exists not to have.
    """
    ok, answer = titan.press_described(token, control)
    if not ok:
        return ok, answer
    if isinstance(answer, dict) and answer.get('answered') is False:
        return titan.key_described(token, 'enter')
    return ok, answer


def _act(work):
    with _LOCK:
        _state['presses'] += 1

    def run():
        ok, answer = work()
        if not ok:
            # A refusal has a sound of its own, because it arrives as prose
            # a listener has to parse otherwise - and the commonest one
            # here is Titan asking its own user for permission.
            icons.play('warn-user')
            _say(str(answer))
            return
        _took(answer)
        say_here(beep=False)
    threading.Thread(target=run, name='TitanAppAct', daemon=True).start()


# --------------------------------------------------------------------------- #
# Saying
# --------------------------------------------------------------------------- #
def row_text(row):
    """One row, whatever shape it arrived in.

    A table's row is a list of cells and a list's row is a string; a
    reader that assumed one of the two would say `['a', 'b']` aloud to
    somebody who cannot see it.
    """
    if isinstance(row, (list, tuple)):
        return ', '.join(str(cell) for cell in row)
    if isinstance(row, dict):
        for name in ('text', 'label', 'name'):
            if row.get(name):
                return str(row[name])
        return ', '.join(str(value) for value in row.values())
    return str(row)


def parts_of(control, at=0, count=0, inner=0):
    """What one control says, as ``[(text, class)]``.

    The user's own semantic classes, so a described application is read
    exactly like every other control this add-on reads - the label as a
    name, what it IS a little lower, its state and value a little higher.
    """
    if not isinstance(control, dict):
        return []
    kind = str(control.get('kind') or '')
    parts = []
    label = str(control.get('label') or '')
    if label:
        parts.append((label, 'name'))
    word = kind_word(kind)
    if word:
        parts.append((word, 'kind'))
    if kind in ('check',):
        parts.append((_('checked') if control.get('value')
                      else _('unchecked'), 'state'))
    rows = _inside(control)
    if rows:
        where = max(0, min(inner, len(rows) - 1))
        parts.append((rows[where], 'value'))
        parts.append((_('{at} of {count}').format(at=where + 1,
                                                  count=len(rows)), 'place'))
    elif kind not in ('check', 'button'):
        value = control.get('value')
        if value not in (None, ''):
            parts.append((str(value), 'value'))
    if count:
        parts.append((_('{at} of {count}').format(at=at + 1, count=count),
                      'place'))
    return parts


def kind_word(kind):
    """What a control IS, in the user's own language."""
    return {
        # Translators: a kind of control in a Titan application.
        'button': _('button'),
        # Translators: a kind of control.
        'check': _('check box'),
        # Translators: a kind of control.
        'choice': _('combo box'),
        # Translators: a kind of control.
        'list': _('list'),
        # Translators: a kind of control.
        'table': _('table'),
        # Translators: a kind of control.
        'tree': _('tree'),
        # Translators: a kind of control.
        'text': _('edit'),
        # Translators: a kind of control.
        'multiline': _('edit, multi line'),
        # Translators: a kind of control.
        'slider': _('slider'),
        # Translators: a kind of control.
        'gauge': _('progress bar'),
        # Translators: a kind of control.
        'tabs': _('tab control'),
        'label': '',
    }.get(str(kind or ''), str(kind or ''))


def say_here(beep=True):
    control = here()
    if control is None:
        return _nothing()
    with _LOCK:
        at = _state['at']
        inner = _state['inner']
        count = len(_controls())
    if beep:
        # **The icon instead of the beep, where there is one.** The two say
        # different things - the beep is WHERE you are in the screen, the
        # icon is WHAT you are on - and Emacspeak is right that the second
        # is worth more: the first is already spoken as "3 of 10", and two
        # sounds on every arrow key is one more than anybody wants. With
        # the icons off the beep is what is left, so nothing is lost by
        # turning them off.
        if not icons.play(icons.for_control(control.get('kind'))):
            _beep(at, count)
    parts = parts_of(control, at=at, count=count, inner=inner)
    _say_parts(parts)
    return True, ', '.join(text for text, _voice in parts)


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


def _nothing():
    # Translators: said when there is nothing at the cursor.
    return False, _('Nothing here')


def _beep(at, count):
    if compat.tones is None:
        return
    span = max(1, (count or 1) - 1)
    where = max(0.0, min(1.0, at / float(span)))
    pitch = int(FREQ_TOP - (FREQ_TOP - FREQ_BOTTOM) * where)
    try:
        compat.tones.beep(pitch, BEEP_MS)
    except Exception:                                # noqa: BLE001
        pass


def _edge():
    if compat.tones is None:
        return
    try:
        compat.tones.beep(220, 30)
    except Exception:                                # noqa: BLE001
        pass


def _cue(on):
    """The same two tones as the other two reviews, so all three agree."""
    if compat.tones is None:
        return
    try:
        compat.tones.beep(660 if on else 440, 40)
    except Exception:                                # noqa: BLE001
        pass


def _say(text, interrupt=True):
    if compat.speech is None:
        return
    try:
        compat.speech.speakMessage(str(text))
    except Exception:                                # noqa: BLE001
        pass
