# -*- coding: utf-8 -*-
"""What a shortcut DOES, said as it is pressed.

Window-Eyes did this: press Control+O in a program and hear "Open" as the
dialog comes up, so a key you half-remember is confirmed the moment it is
used and a key you pressed by mistake is named before its effect arrives.
It did it out of `.key` files - one hand-written table per program, which
is the reason it was rare. This does it out of what the PROGRAM says
about its own keys, and out of nothing else that has to be written:

1. **The program's own menu.** A Win32 menu carries every accelerator in
   the item text itself - "&Open...\\tCtrl+O" - and `GetMenu` /
   `GetSubMenu` / `GetMenuStringW` read the whole tree in a few
   milliseconds without opening a single menu on the screen. That is the
   program's own word for what the key does, in the user's own language,
   and it covers every classic Windows program there is.
2. **The focused control's own accelerator** (UI Automation's
   `AcceleratorKey`), where the reader underneath can ask for it.
3. **A reader module's ``shortcuts``** - data a module may carry for a
   program whose menus say nothing, ``{"control+shift+p": "Command
   palette"}``. Data in the same file as everything else the module knows,
   not a `.key` file.
4. **What the key means everywhere** (:data:`STANDARD`): Control+C is
   Copy in every program that has not said otherwise, and a program that
   HAS said otherwise is answered first.

Nothing here is on the key's own path: the reader sees the key, the
program gets it exactly as it would have, and the word is queued a moment
later - after the program has answered, so "Open" is followed by the
dialog it opened rather than talking over it. A key nothing knows about
says nothing at all.
"""

import ctypes
import threading
import time

from . import i18n

_ = i18n.install(globals())

_LOCK = threading.RLock()

#: How long a program's menu tree is believed before it is read again.
MENU_TTL = 8.0

#: The keys this speaks for on their own - the function keys. A letter
#: alone is typing, an arrow alone is moving; a function key alone is a
#: command, and one whose meaning the user is unsure of.
BARE_KEYS = frozenset('f%d' % n for n in range(1, 13))

#: The keys it never speaks for whatever the modifiers: moving, editing
#: and the modifiers themselves. Control with an arrow is a caret jump the
#: reader already follows; saying "word right" over it would be noise.
NEVER = frozenset(('up', 'down', 'left', 'right', 'home', 'end', 'pageup',
                   'pagedown', 'tab', 'shift', 'control', 'alt', 'windows',
                   'capslock', 'numlock', 'backspace', 'delete', 'insert',
                   'escape', 'enter', 'return', 'space', 'applications',
                   'printscreen', 'scrolllock', 'pause'))

_state = {'on': True, 'said': 0, 'asked': 0, 'menus_read': 0}
_menu_cache = {}


def _text(value):
    return str(value or '').strip()


# --------------------------------------------------------------------------- #
# The key
# --------------------------------------------------------------------------- #
_MODIFIER_WORDS = {
    'ctrl': 'control', 'control': 'control', 'strg': 'control',
    'ctl': 'control', 'alt': 'alt', 'shift': 'shift', 'umschalt': 'shift',
    'win': 'windows', 'windows': 'windows', 'nvda': 'nvda',
}
_KEY_WORDS = {
    'del': 'delete', 'delete': 'delete', 'ins': 'insert', 'insert': 'insert',
    'esc': 'escape', 'escape': 'escape', 'return': 'enter', 'enter': 'enter',
    'pgup': 'pageup', 'pageup': 'pageup', 'pgdn': 'pagedown',
    'pagedown': 'pagedown', 'bksp': 'backspace', 'backspace': 'backspace',
    'space': 'space', 'spacebar': 'space', 'plus': '+', 'minus': '-',
    'uparrow': 'up', 'downarrow': 'down', 'leftarrow': 'left',
    'rightarrow': 'right', 'numpadenter': 'enter',
}


def identifier(key, ctrl=False, alt=False, shift=False, windows=False):
    """One spelling for a key with its modifiers: ``control+shift+s``."""
    key = _KEY_WORDS.get(_text(key).lower(), _text(key).lower())
    if not key:
        return ''
    parts = []
    if ctrl:
        parts.append('control')
    if alt:
        parts.append('alt')
    if shift:
        parts.append('shift')
    if windows:
        parts.append('windows')
    parts.append(key)
    return '+'.join(parts)


def from_text(text):
    """A shortcut as a program writes it - ``Ctrl+Shift+S``, ``Strg+O``,
    ``F5`` - into :func:`identifier`'s spelling, or '' when it is not one."""
    text = _text(text).replace(' ', '')
    if not text:
        return ''
    pieces = [piece for piece in text.split('+') if piece] \
        if text != '+' else ['+']
    if text.endswith('++'):
        pieces = [piece for piece in text[:-2].split('+') if piece] + ['+']
    ctrl = alt = shift = windows = False
    key = ''
    for piece in pieces:
        low = piece.lower()
        if low in _MODIFIER_WORDS:
            which = _MODIFIER_WORDS[low]
            ctrl = ctrl or which == 'control'
            alt = alt or which == 'alt'
            shift = shift or which == 'shift'
            windows = windows or which == 'windows'
        else:
            key = low
    if not key:
        return ''
    return identifier(key, ctrl, alt, shift, windows)


def worth_saying(key, ctrl=False, alt=False, shift=False):
    """Whether this key is a command somebody would want named.

    Control with anything, Alt+F4, and a function key alone. Alt with a
    letter is a menu opening, and the menu names itself; a letter alone is
    typing; Shift with a letter is a capital.
    """
    key = _KEY_WORDS.get(_text(key).lower(), _text(key).lower())
    if not key or key in NEVER:
        return False
    if ctrl:
        return True
    if key in BARE_KEYS:
        return True
    if alt and key == 'f4':
        return True
    return False


# --------------------------------------------------------------------------- #
# What the key means everywhere
# --------------------------------------------------------------------------- #
def standard():
    """The meanings a key has in every program that has not said otherwise.

    A function rather than a table so the words are translated in the
    user's language at the moment they are asked for.
    """
    return {
        # Translators: what a standard shortcut does.
        'control+o': _('Open'),
        'control+s': _('Save'),
        'control+shift+s': _('Save as'),
        'control+n': _('New'),
        'control+shift+n': _('New window'),
        'control+w': _('Close'),
        'control+f4': _('Close the document'),
        'alt+f4': _('Close the window'),
        'control+p': _('Print'),
        'control+z': _('Undo'),
        'control+y': _('Redo'),
        'control+shift+z': _('Redo'),
        'control+x': _('Cut'),
        'control+c': _('Copy'),
        'control+v': _('Paste'),
        'control+shift+v': _('Paste as plain text'),
        'control+a': _('Select all'),
        'control+f': _('Find'),
        'control+h': _('Replace'),
        'control+g': _('Go to'),
        'control+b': _('Bold'),
        'control+i': _('Italic'),
        'control+u': _('Underline'),
        'control+t': _('New tab'),
        'control+shift+t': _('Reopen the closed tab'),
        'control+tab': _('Next tab'),
        'control+shift+tab': _('Previous tab'),
        'control+r': _('Refresh'),
        'control+l': _('Address'),
        'control+d': _('Bookmark'),
        'control+e': _('Search'),
        'control+k': _('Search'),
        'control+j': _('Downloads'),
        'control+shift+delete': _('Clear browsing data'),
        'control++': _('Zoom in'),
        'control+-': _('Zoom out'),
        'control+0': _('Actual size'),
        'f1': _('Help'),
        'f2': _('Rename'),
        'f3': _('Find next'),
        'f5': _('Refresh'),
        'f6': _('Next pane'),
        'f10': _('Menu bar'),
        'f11': _('Full screen'),
        'f12': _('Developer tools'),
    }


# --------------------------------------------------------------------------- #
# The program's own menu
# --------------------------------------------------------------------------- #
def _user32():
    user32 = ctypes.windll.user32
    user32.GetMenu.restype = ctypes.c_void_p
    user32.GetSubMenu.restype = ctypes.c_void_p
    user32.GetMenuItemCount.restype = ctypes.c_int
    return user32


def _clean_label(text):
    """"&Open..." -> "Open": the accelerator ampersand is for a mouse user
    reading the underline, the dots say a dialog follows."""
    text = _text(text).replace('&&', '\x00').replace('&', '').replace('\x00', '&')
    while text.endswith('.'):
        text = text[:-1]
    return text.strip()


def read_menu(hwnd):
    """``{identifier: label}`` for every accelerator in a window's menu.

    The Win32 menu bar and every submenu under it, read out of the menu
    handles without showing anything. A window with no menu, or one that
    draws its own (a ribbon, a browser), answers ``{}`` in a microsecond.
    """
    found = {}
    try:
        hwnd = int(hwnd or 0)
    except (TypeError, ValueError):
        return found
    if not hwnd:
        return found
    try:
        user32 = _user32()
        top = user32.GetMenu(ctypes.c_void_p(hwnd))
    except Exception:                                # noqa: BLE001
        return found
    if not top:
        return found
    with _LOCK:
        _state['menus_read'] += 1
    _walk_menu(user32, int(top), found, 0)
    return found


def _walk_menu(user32, menu, found, depth):
    if depth > 8 or not menu:
        return
    try:
        count = int(user32.GetMenuItemCount(ctypes.c_void_p(menu)))
    except Exception:                                # noqa: BLE001
        return
    for index in range(max(0, min(count, 200))):
        buffer = ctypes.create_unicode_buffer(256)
        try:
            user32.GetMenuStringW(ctypes.c_void_p(menu), index, buffer, 256,
                                  0x400)           # MF_BYPOSITION
        except Exception:                            # noqa: BLE001
            continue
        text = str(buffer.value or '')
        if '\t' in text:
            label, _tab, accelerator = text.partition('\t')
            key = from_text(accelerator)
            label = _clean_label(label)
            if key and label and key not in found:
                found[key] = label
        try:
            sub = user32.GetSubMenu(ctypes.c_void_p(menu), index)
        except Exception:                            # noqa: BLE001
            sub = None
        if sub:
            _walk_menu(user32, int(sub), found, depth + 1)


def menu_of(hwnd):
    """`read_menu`, remembered for `MENU_TTL` per window."""
    now = time.time()
    with _LOCK:
        cached = _menu_cache.get(hwnd)
        if cached and now - cached[0] < MENU_TTL:
            return cached[1]
    found = read_menu(hwnd)
    with _LOCK:
        _menu_cache[hwnd] = (now, found)
        if len(_menu_cache) > 32:
            oldest = min(_menu_cache, key=lambda h: _menu_cache[h][0])
            _menu_cache.pop(oldest, None)
    return found


# --------------------------------------------------------------------------- #
# What it does
# --------------------------------------------------------------------------- #
def describe(key, ctrl=False, alt=False, shift=False, hwnd=0,
             module=None, focused_accelerator=''):
    """What this key does in the program in front, or ''.

    The program's own menu first, then the focused control's own
    accelerator, then the reader module's ``shortcuts``, then what the key
    means everywhere.
    """
    wanted = identifier(key, ctrl, alt, shift)
    if not wanted:
        return ''
    with _LOCK:
        _state['asked'] += 1
    try:
        own = menu_of(hwnd) if hwnd else {}
    except Exception:                                # noqa: BLE001
        own = {}
    if wanted in own:
        return own[wanted]
    if focused_accelerator and from_text(focused_accelerator) == wanted:
        # The control's own key IS this key: what it does is press it.
        return ''
    try:
        table = (module.get('shortcuts') if isinstance(module, dict)
                 else getattr(module, 'data', {}).get('shortcuts')) or {}
        for spelled, meaning in table.items():
            if from_text(spelled) == wanted and _text(meaning):
                return _text(meaning)
    except Exception:                                # noqa: BLE001
        pass
    return standard().get(wanted, '')


def consider(key, ctrl, alt, shift, hwnd, say, module=None, delay=0.06):
    """The whole thing, from a key seen by the reader: decide, look up on
    a worker, and hand the word to ``say`` a moment later. True when a
    word will be said."""
    if not switched_on() or not worth_saying(key, ctrl, alt, shift):
        return False

    def later():
        try:
            word = describe(key, ctrl, alt, shift, hwnd, module)
        except Exception:                            # noqa: BLE001
            word = ''
        if word:
            with _LOCK:
                _state['said'] += 1
            try:
                say(word)
            except Exception:                        # noqa: BLE001
                pass
    timer = threading.Timer(max(0.0, float(delay)), later)
    timer.daemon = True
    timer.start()
    return True


def switched_on():
    """The user's switch, and this module's own - either says no."""
    with _LOCK:
        if not _state['on']:
            return False
    try:
        from . import switchboard
        return bool(switchboard.read('speakShortcuts', True))
    except Exception:                                # noqa: BLE001
        return True


def set_switched_on(on):
    with _LOCK:
        _state['on'] = bool(on)
    try:
        from . import switchboard
        switchboard.write('speakShortcuts', bool(on))
    except Exception:                                # noqa: BLE001
        pass
    return bool(on)


def report():
    with _LOCK:
        found = dict(_state)
        found['cached_menus'] = len(_menu_cache)
    return found


def forget():
    with _LOCK:
        _menu_cache.clear()
        _state.update({'said': 0, 'asked': 0, 'menus_read': 0, 'on': True})
