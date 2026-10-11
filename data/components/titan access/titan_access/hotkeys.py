# -*- coding: utf-8 -*-
"""The reader's own shortcut: written as text, registered with Windows,
and CAUGHT when the user sets it.

A shortcut is kept as ``ctrl+shift+t`` (`General/ToggleHotkey`): the
modifiers in a fixed order, then one key. It is what `init.py`'s listener
registers with ``RegisterHotKey``, what the settings page's field shows,
and what the walked settings capture - Enter on the row, then the
combination itself, exactly as a hotkey field in Windows takes one.

**Capturing goes through the reader's own keyboard hook**
(`keyboard_hook._process` asks :func:`capture_key` first), because the
walked settings have no window to type into, and because a combination
like Control+Shift+T would otherwise reach the program in front, or fire
the very shortcut being changed. Escape alone leaves it as it was.
"""

import sys
import threading

DEFAULT = 'ctrl+shift+t'

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

_MODS = (('ctrl', MOD_CONTROL), ('alt', MOD_ALT), ('shift', MOD_SHIFT),
         ('win', MOD_WIN))
_ALIASES = {'control': 'ctrl', 'menu': 'alt', 'windows': 'win',
            'super': 'win', 'meta': 'win'}

#: vk -> the name a shortcut is written with, beyond letters, digits and F-keys.
_KEY_NAMES = {
    0x08: 'backspace', 0x09: 'tab', 0x0D: 'enter', 0x1B: 'escape',
    0x20: 'space', 0x21: 'pageup', 0x22: 'pagedown', 0x23: 'end',
    0x24: 'home', 0x25: 'left', 0x26: 'up', 0x27: 'right', 0x28: 'down',
    0x2D: 'insert', 0x2E: 'delete', 0x13: 'pause',
    0xBA: ';', 0xBB: '=', 0xBC: ',', 0xBD: '-', 0xBE: '.', 0xBF: '/',
    0xC0: '`', 0xDB: '[', 0xDC: '\\', 0xDD: ']', 0xDE: "'",
}
_NUMPAD = {0x60 + n: 'numpad%d' % n for n in range(10)}
_KEY_NAMES.update(_NUMPAD)
_BY_NAME = {name: vk for vk, name in _KEY_NAMES.items()}
_BY_NAME.update({'return': 0x0D, 'esc': 0x1B, 'del': 0x2E, 'ins': 0x2D})

#: The vks that are modifiers and never the key of a shortcut.
MODIFIER_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5,
                0x5B, 0x5C}

#: Said in place of the written name ("Control+Shift+T").
_SPOKEN_MODS = {'ctrl': 'Control', 'alt': 'Alt', 'shift': 'Shift',
                'win': 'Windows'}


def key_name(vk):
    """The written name of one non-modifier key, or ''."""
    vk = int(vk or 0)
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        return chr(vk).lower()
    if 0x70 <= vk <= 0x87:
        return 'f%d' % (vk - 0x6F)
    return _KEY_NAMES.get(vk, '')


def vk_of(name):
    """The virtual key of a written key name, or 0."""
    name = str(name or '').strip().lower()
    if len(name) == 1 and (name.isalpha() or name.isdigit()):
        return ord(name.upper())
    if name.startswith('f') and name[1:].isdigit():
        number = int(name[1:])
        return 0x6F + number if 1 <= number <= 24 else 0
    return _BY_NAME.get(name, 0)


def normalize(text):
    """``'Shift + Ctrl+T'`` -> ``'ctrl+shift+t'``; '' for what is not one."""
    found = parse(text)
    if found is None:
        return ''
    mods, vk = found
    names = [name for name, bit in _MODS if mods & bit]
    return '+'.join(names + [key_name(vk)])


def parse(text):
    """``(RegisterHotKey modifiers, vk)``, or None.

    One key, at least one of Control, Alt or Windows in front of it - or a
    function key on its own. Anything else would take a key the user types.
    """
    parts = [p.strip().lower() for p in str(text or '').replace(' ', '')
             .split('+')]
    # "ctrl++" is Control and the plus key; '+' itself is not written.
    parts = [p for p in parts if p]
    if not parts:
        return None
    mods = 0
    key = None
    for part in parts:
        part = _ALIASES.get(part, part)
        bit = dict(_MODS).get(part)
        if bit:
            mods |= bit
            continue
        if key is not None:
            return None
        key = vk_of(part)
        if not key:
            return None
    if key is None:
        return None
    if not (mods & (MOD_CONTROL | MOD_ALT | MOD_WIN)) and \
            not 0x70 <= key <= 0x87:
        return None
    return mods, key


def spoken(text):
    """How a shortcut is said and shown: ``Control+Shift+T``."""
    normal = normalize(text)
    if not normal:
        return ''
    out = []
    for part in normal.split('+'):
        if part in _SPOKEN_MODS:
            out.append(_SPOKEN_MODS[part])
        elif len(part) == 1:
            out.append(part.upper())
        else:
            out.append(part[:1].upper() + part[1:])
    return '+'.join(out)


def from_event(key_code, ctrl, alt, shift, win=False):
    """A wx key event's combination, written; '' while only modifiers
    are down or it is not a usable shortcut."""
    try:
        import wx
        special = {wx.WXK_BACK: 0x08, wx.WXK_TAB: 0x09, wx.WXK_RETURN: 0x0D,
                   wx.WXK_ESCAPE: 0x1B, wx.WXK_SPACE: 0x20,
                   wx.WXK_PAGEUP: 0x21, wx.WXK_PAGEDOWN: 0x22,
                   wx.WXK_END: 0x23, wx.WXK_HOME: 0x24, wx.WXK_LEFT: 0x25,
                   wx.WXK_UP: 0x26, wx.WXK_RIGHT: 0x27, wx.WXK_DOWN: 0x28,
                   wx.WXK_INSERT: 0x2D, wx.WXK_DELETE: 0x2E}
        vk = special.get(key_code)
        if vk is None and wx.WXK_F1 <= key_code <= wx.WXK_F24:
            vk = 0x70 + (key_code - wx.WXK_F1)
        if vk is None and wx.WXK_NUMPAD0 <= key_code <= wx.WXK_NUMPAD9:
            vk = 0x60 + (key_code - wx.WXK_NUMPAD0)
    except Exception:                                # noqa: BLE001
        vk = None
    if vk is None and 0 < key_code < 256:
        char = chr(key_code).upper()
        if char.isalnum():
            vk = ord(char)
        else:
            vk = _BY_NAME.get(chr(key_code), 0)
    if not vk:
        return ''
    names = [name for name, on in (('ctrl', ctrl), ('alt', alt),
                                   ('shift', shift), ('win', win)) if on]
    return normalize('+'.join(names + [key_name(vk)]))


# --------------------------------------------------------------------------- #
# Who registers it - told when it changes
# --------------------------------------------------------------------------- #
_listeners = []

#: True while the settings page's hotkey field has the keyboard: the
#: shortcut in force is being typed into it, not pressed.
field_focused = False


def on_change(callback):
    """``callback()`` whenever the shortcut is set (the global listener)."""
    if callback not in _listeners:
        _listeners.append(callback)


def changed():
    for callback in list(_listeners):
        try:
            callback()
        except Exception as error:                   # noqa: BLE001
            print('[TitanAccess] hotkey change: %s' % error)


def current():
    """The shortcut in force, written; the default when none is set or the
    one written cannot be registered."""
    try:
        from titan_access.settings_store import get_settings
        text = get_settings().get('General', 'ToggleHotkey', DEFAULT)
    except Exception:                                # noqa: BLE001
        text = DEFAULT
    return normalize(text) or DEFAULT


# --------------------------------------------------------------------------- #
# Capturing a combination through the reader's keyboard hook
# --------------------------------------------------------------------------- #
_LOCK = threading.Lock()
_capture = {'on': None, 'swallow_up': set()}


def begin_capture(on_done):
    """Take the next combination pressed. ``on_done(text)`` gets it, or
    None when Escape left it as it was. Runs on the hook's thread, so it
    must hand real work on."""
    with _LOCK:
        _capture['on'] = on_done
        _capture['swallow_up'] = set()


def capturing():
    with _LOCK:
        return _capture['on'] is not None


def cancel_capture():
    with _LOCK:
        _capture['on'] = None


def _held(vk):
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetAsyncKeyState(int(vk)) & 0x8000)
    except Exception:                                # noqa: BLE001
        return False


def capture_key(vk, is_down):
    """Asked by the keyboard hook first. None: not capturing, or a
    modifier (it goes on as usual and is read from the hardware). True:
    the key was taken."""
    with _LOCK:
        done = _capture['on']
        if done is None:
            if not is_down and vk in _capture['swallow_up']:
                _capture['swallow_up'].discard(vk)
                return True
            return None
    if vk in MODIFIER_VKS:
        return None
    if not is_down:
        return True
    name = key_name(vk)
    ctrl, alt = _held(0x11), _held(0x12)
    shift, win = _held(0x10), (_held(0x5B) or _held(0x5C))
    with _LOCK:
        _capture['swallow_up'].add(vk)
    if vk == 0x1B and not (ctrl or alt or shift or win):
        with _LOCK:
            _capture['on'] = None
        _hand_on(done, None)
        return True
    names = [n for n, on in (('ctrl', ctrl), ('alt', alt), ('shift', shift),
                              ('win', win)) if on]
    text = normalize('+'.join(names + [name])) if name else ''
    if not text:
        _hand_on(done, '')
        return True
    with _LOCK:
        _capture['on'] = None
    _hand_on(done, text)
    return True


def _hand_on(done, text):
    def run():
        try:
            done(text)
        except Exception as error:                   # noqa: BLE001
            print('[TitanAccess] hotkey capture: %s' % error)
    threading.Thread(target=run, daemon=True,
                     name='TitanAccessHotkeyCapture').start()
