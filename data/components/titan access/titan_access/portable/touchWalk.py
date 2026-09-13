# -*- coding: utf-8 -*-
"""The trackpad in every walked list: explore with a finger, flick to move.

The virtual window, the palette (and a message, which is a palette page)
and the OCR review are the lists this add-on asks people to learn, and
until now they were keyboard-only: the touchpad, which :mod:`trackpad`
turns into a touch screen, went on driving NVDA's own object navigation
underneath them. So this is the same interaction a THIRD way, after the
keys and the numpad - and the pad replaces the mouse in a walked list
entirely, which is what the user asked for.

**One finger is exploration.** A finger on the pad is a finger on the
screen (the pad is mapped onto it absolutely), so hovering says the control
under the finger - the virtual window finds the smallest control whose
rectangle holds the point, the OCR review the word drawn there, and the
palette, which has no geometry, maps the height of the screen onto its
rows so the top of the pad is the first row and the bottom the last. A
double tap presses what the finger found, and the flicks are the arrows.

**More fingers are the keys the arrows are not**, and every 3- and
4-finger swipe means something, as asked:

    1 finger   hover        explore (say what is under the finger)
               tap          say the row again
               double tap   Enter
               flick L/R    Left / Right (by layout)
               flick U/D    Up / Down (by layout)
    2 fingers  flick L/R    Shift + Left / Right (the other way)
               flick U/D    Page Up / Page Down
               tap          Escape (back one level)
    3 fingers  flick L/R    the TOP corners: top left / top right
               flick U/D    the previous / next layout (Numpad 4 / 6)
               tap          click with the mouse (Numpad 5)
    4 fingers  flick L/R    the BOTTOM corners: bottom left / bottom right
               flick U/D    Home / End
               tap          leave the list

Three fingers reach the top row of corners and four the bottom row, so a
corner is "how many fingers, which way": more fingers, lower down.

**Windows has 3- and 4-finger gestures of its own** (switching programs,
task view, virtual desktops) and the pad is only LISTENED to, so both
happen at once until those are set to "Nothing" in Settings > Devices >
Touchpad. That is Windows' setting to change and this module cannot.

The names are NVDA's own gesture actions (``flickleft``,
``2finger_flickup``, ``hover``, ``double_tap``), which is what
:mod:`trackpad` feeds NVDA's tracker to produce - nothing here invents a
vocabulary - and the plugin binds them only while a list is really up, the
discipline every borrowed key follows.
"""

import threading

from . import i18n

_ = i18n.install(globals())

_LOCK = threading.RLock()
_state = {'handled': 0, 'unbound': 0, 'explored': 0, 'last': ''}

#: Every action this answers, in NVDA's spelling. The plugin binds exactly
#: these, and a test reads this table so a gesture answered here is one
#: that is really bound.
ACTIONS = (
    'hover', 'hoverdown', 'tap', 'double_tap',
    'flickleft', 'flickright', 'flickup', 'flickdown',
    '2finger_flickleft', '2finger_flickright',
    '2finger_flickup', '2finger_flickdown', '2finger_tap',
    '3finger_flickleft', '3finger_flickright',
    '3finger_flickup', '3finger_flickdown', '3finger_tap',
    '4finger_flickleft', '4finger_flickright',
    '4finger_flickup', '4finger_flickdown', '4finger_tap',
)


def report():
    with _LOCK:
        return dict(_state, walker=walker())


def action_of(identifier):
    """``'2finger_flickleft'`` out of ``'ts(object):2finger_flickleft'``."""
    name = str(identifier or '')
    if ':' in name:
        name = name.rsplit(':', 1)[1]
    return name.strip().lower()


# --------------------------------------------------------------------------- #
# Which list is up
# --------------------------------------------------------------------------- #
def walker():
    """The name of the walked list that has the keys right now, or ''."""
    for name in ('palette', 'virtualWindow', 'ocrReview'):
        try:
            module = _module(name)
            if module is not None and module.reviewing():
                return name
        except Exception:                            # noqa: BLE001
            continue
    return ''


def _module(name):
    from importlib import import_module
    try:
        return import_module('.' + name, __package__)
    except Exception:                                # noqa: BLE001
        return None


def screen_size():
    """``(width, height)`` of the screen, for the lists with no geometry."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        if width > 0 and height > 0:
            return int(width), int(height)
    except Exception:                                # noqa: BLE001
        pass
    return 1920, 1080


# --------------------------------------------------------------------------- #
# Answering a gesture
# --------------------------------------------------------------------------- #
def handle(action, x=None, y=None):
    """One gesture, answered by whichever list is up. ``(handled, said)``.

    ``said`` is what the walker answered and may be '' - most moves speak
    for themselves. ``handled`` is False when no list is up, which is the
    plugin's cue to give the gestures back.
    """
    name = walker()
    if not name:
        with _LOCK:
            _state['unbound'] += 1
        return False, ''
    module = _module(name)
    action = action_of(action)
    with _LOCK:
        _state['handled'] += 1
        _state['last'] = action
    try:
        if action in ('hover', 'hoverdown'):
            if x is None or y is None:
                return True, ''
            with _LOCK:
                _state['explored'] += 1
            return True, _said(module.explore(int(x), int(y)))
        table = _TABLE.get(name) or {}
        found = table.get(action)
        if found is None:
            return True, ''
        return True, _said(found(module))
    except Exception:                                # noqa: BLE001
        return True, ''


def _said(answer):
    if isinstance(answer, tuple) and len(answer) == 2:
        return str(answer[1] or '')
    return ''


def _layout(module, delta):
    try:
        from . import virtualWindow
        return virtualWindow.layout_cycle(delta)
    except Exception:                                # noqa: BLE001
        return False, ''


def _common(module):
    """What every list answers the same way."""
    return {
        'tap': lambda m: m.say_here(beep=False)
        if hasattr(m, 'say_here') else m.say_line(),
        'flickup': lambda m: m.move(-1) if hasattr(m, 'move')
        else m.move_line(-1),
        'flickdown': lambda m: m.move(1) if hasattr(m, 'move')
        else m.move_line(1),
        '3finger_flickup': lambda m: _layout(m, -1),
        '3finger_flickdown': lambda m: _layout(m, 1),
        '4finger_flickup': lambda m: m.move_end(False),
        '4finger_flickdown': lambda m: m.move_end(True),
    }


def _virtual():
    table = _common(None)
    table.update({
        'double_tap': lambda m: m.activate(),
        'flickleft': lambda m: m.move_across(-1),
        'flickright': lambda m: m.move_across(1),
        '2finger_flickleft': lambda m: m.move_across_shift(-1),
        '2finger_flickright': lambda m: m.move_across_shift(1),
        '2finger_flickup': lambda m: m.move_page(-1),
        '2finger_flickdown': lambda m: m.move_page(1),
        '2finger_tap': lambda m: (m.close_menu() if m.in_a_menu()
                                  else m.stop()),
        '3finger_flickleft': lambda m: m.move_diagonal(-1, -1),
        '3finger_flickright': lambda m: m.move_diagonal(1, -1),
        '3finger_tap': lambda m: m.click_mouse(),
        '4finger_flickleft': lambda m: m.move_diagonal(-1, 1),
        '4finger_flickright': lambda m: m.move_diagonal(1, 1),
        '4finger_tap': lambda m: m.stop(),
    })
    return table


def _palette():
    table = _common(None)
    table.update({
        'double_tap': lambda m: m.activate(),
        'flickleft': lambda m: m.move_across(-1),
        'flickright': lambda m: m.move_across(1),
        '2finger_flickleft': lambda m: m.move_across_shift(-1),
        '2finger_flickright': lambda m: m.move_across_shift(1),
        '2finger_flickup': lambda m: m.move(-10),
        '2finger_flickdown': lambda m: m.move(10),
        '2finger_tap': lambda m: m.back(),
        '3finger_flickleft': lambda m: m.move_corner(-1, -1),
        '3finger_flickright': lambda m: m.move_corner(1, -1),
        '3finger_tap': lambda m: m.activate(),
        '4finger_flickleft': lambda m: m.move_corner(-1, 1),
        '4finger_flickright': lambda m: m.move_corner(1, 1),
        '4finger_tap': lambda m: m.stop(),
    })
    return table


def _ocr():
    table = _common(None)
    table.update({
        'double_tap': lambda m: m.click(),
        'flickleft': lambda m: m.move_word(-1),
        'flickright': lambda m: m.move_word(1),
        '2finger_flickleft': lambda m: m.move_end(False),
        '2finger_flickright': lambda m: m.move_end(True),
        '2finger_flickup': lambda m: m.move_page(-1),
        '2finger_flickdown': lambda m: m.move_page(1),
        '2finger_tap': lambda m: m.stop(),
        '3finger_flickleft': lambda m: m.move_corner(-1, -1),
        '3finger_flickright': lambda m: m.move_corner(1, -1),
        '3finger_tap': lambda m: m.click(),
        '4finger_flickleft': lambda m: m.move_corner(-1, 1),
        '4finger_flickright': lambda m: m.move_corner(1, 1),
        '4finger_tap': lambda m: m.stop(),
        # A picture has no words to page by; Home and End are the line's.
        '4finger_flickup': lambda m: m.move_line(-10 ** 6),
        '4finger_flickdown': lambda m: m.move_line(10 ** 6),
    })
    return table


_TABLE = {'virtualWindow': _virtual(), 'palette': _palette(),
          'ocrReview': _ocr()}


def forget():
    with _LOCK:
        for key in ('handled', 'unbound', 'explored'):
            _state[key] = 0
        _state['last'] = ''
