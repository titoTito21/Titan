"""Titan Access on Linux: the keyboard, through AT-SPI's keystroke listener.

On Windows the reader owns the keyboard with a low-level hook. On Linux a
process cannot hook the keyboard - but the accessibility bus can be asked
to deliver every keystroke to a listener BEFORE the application sees it,
and to let the listener consume it (``Atspi.register_keystroke_listener``
with ``CANCONSUME``, which is how Orca takes Insert and CapsLock for
itself). Under XWayland and X11 that covers every X application, which a
Titan window is.

What arrives is an X keysym plus a hardware code; :func:`vk_of` turns it
into the Windows virtual-key code and the "extended" flag the reader's
:class:`~titan_access.keyboard_hook.KeyboardHook` has always been fed,
so the whole of its routing - the reader modifier, the chords, the
gestures, typing echo - is untouched.
"""
import os
import sys

from titan_access import atspi_focus

_TRACE = bool(os.environ.get('TITAN_ACCESS_TRACE'))

IS_LINUX = sys.platform.startswith('linux')

LLKHF_EXTENDED = 0x01
LLKHF_UP = 0x80

# X keysym -> (virtual key, extended). Letters, digits and punctuation are
# handled by vk_of(); this table is the rest.
_SPECIAL = {
    0xff63: (0x2D, True),   # Insert
    0xff9e: (0x2D, False),  # KP_Insert (NumLock off)
    0xffff: (0x2E, True),   # Delete
    0xff9f: (0x2E, False),  # KP_Delete
    0xff50: (0x24, True), 0xff95: (0x24, False),   # Home, KP_Home
    0xff57: (0x23, True), 0xff9c: (0x23, False),   # End, KP_End
    0xff55: (0x21, True), 0xff9a: (0x21, False),   # PageUp, KP_Prior
    0xff56: (0x22, True), 0xff9b: (0x22, False),   # PageDown, KP_Next
    0xff51: (0x25, True), 0xff96: (0x25, False),   # Left
    0xff52: (0x26, True), 0xff97: (0x26, False),   # Up
    0xff53: (0x27, True), 0xff98: (0x27, False),   # Right
    0xff54: (0x28, True), 0xff99: (0x28, False),   # Down
    0xff9d: (0x0C, False),  # KP_Begin (numpad 5, NumLock off)
    0xffab: (0x6B, False), 0xffad: (0x6D, False),  # KP_Add, KP_Subtract
    0xffaa: (0x6A, False), 0xffaf: (0x6F, True),   # KP_Multiply, KP_Divide
    0xffae: (0x6E, False), 0xffac: (0x6E, False),  # KP_Decimal, KP_Separator
    0xff8d: (0x0D, True),   # KP_Enter
    0xff0d: (0x0D, False),  # Return
    0xff09: (0x09, False), 0xfe20: (0x09, False),  # Tab, ISO_Left_Tab
    0xff1b: (0x1B, False),  # Escape
    0xff08: (0x08, False),  # BackSpace
    0x0020: (0x20, False),  # space
    0xffe1: (0xA0, False), 0xffe2: (0xA1, False),  # Shift_L, Shift_R
    0xffe3: (0xA2, False), 0xffe4: (0xA3, True),   # Control_L, Control_R
    0xffe9: (0xA4, False), 0xffea: (0xA5, True),   # Alt_L, Alt_R
    0xfe03: (0xA5, True),   # ISO_Level3_Shift (AltGr)
    0xffe5: (0x14, False),  # Caps_Lock
    0xff7f: (0x90, True),   # Num_Lock
    0xff14: (0x91, False),  # Scroll_Lock
    0xffeb: (0x5B, True), 0xffec: (0x5C, True),    # Super_L, Super_R
    0xff67: (0x5D, True),   # Menu
    0xff61: (0x2C, False),  # Print
    0xff13: (0x13, False),  # Pause
}
for _i in range(12):
    _SPECIAL[0xffbe + _i] = (0x70 + _i, False)     # F1..F12
for _i in range(10):
    _SPECIAL[0xffb0 + _i] = (0x60 + _i, False)     # KP_0..KP_9

# US keyboard punctuation, shifted and unshifted, to the OEM virtual keys.
_PUNCT = {
    ';': 0xBA, ':': 0xBA, '=': 0xBB, '+': 0xBB, ',': 0xBC, '<': 0xBC,
    '-': 0xBD, '_': 0xBD, '.': 0xBE, '>': 0xBE, '/': 0xBF, '?': 0xBF,
    '`': 0xC0, '~': 0xC0, '[': 0xDB, '{': 0xDB, '\\': 0xDC, '|': 0xDC,
    ']': 0xDD, '}': 0xDD, "'": 0xDE, '"': 0xDE,
    '!': 0x31, '@': 0x32, '#': 0x33, '$': 0x34, '%': 0x35, '^': 0x36,
    '&': 0x37, '*': 0x38, '(': 0x39, ')': 0x30,
}

# Polish (and other Latin) letters typed with AltGr: the base letter's key.
_ACCENTED = {
    'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n', 'ó': 'o', 'ś': 's',
    'ź': 'x', 'ż': 'z', 'ä': 'a', 'ö': 'o', 'ü': 'u', 'ß': 's', 'é': 'e',
    'è': 'e', 'ê': 'e', 'à': 'a', 'ç': 'c', 'ñ': 'n', 'í': 'i', 'ú': 'u',
    'á': 'a', 'ů': 'u', 'ř': 'r', 'š': 's', 'č': 'c', 'ž': 'z', 'ě': 'e',
    'ý': 'y', 'ő': 'o', 'ű': 'u', 'ï': 'i', 'ô': 'o', 'â': 'a', 'û': 'u',
    'ø': 'o', 'å': 'a', 'æ': 'a',
}


def vk_of(keysym):
    """(virtual key, extended) for an X keysym, or (0, False) for none."""
    if keysym in _SPECIAL:
        return _SPECIAL[keysym]
    if 0x20 <= keysym <= 0x7e:
        char = chr(keysym)
        if char.isalpha():
            return ord(char.upper()), False
        if char.isdigit():
            return ord(char), False
        if char in _PUNCT:
            return _PUNCT[char], False
        return 0, False
    # A Latin letter with a diacritic arrives as its own keysym (Latin-2 is
    # 0x1xx, and Unicode keysyms carry 0x1000000): the key it sits on.
    try:
        char = _keysym_char(keysym)
    except Exception:                                # noqa: BLE001
        char = ''
    if char:
        base = _ACCENTED.get(char.lower())
        if base:
            return ord(base.upper()), False
    return 0, False


def _keysym_char(keysym):
    if keysym & 0x1000000:
        return chr(keysym & 0xffffff)
    if 0x100 <= keysym <= 0x1ff:                     # Latin-2
        try:
            from gi.repository import Gdk
            code = Gdk.keyval_to_unicode(keysym)
            return chr(code) if code else ''
        except Exception:                            # noqa: BLE001
            return ''
    return ''


_listener = None
_registered = []
_replies = {'yes': 0, 'no': 0}
_hook = None


def start(hook):
    """Feed *hook* (a KeyboardHook) every keystroke; True when listening."""
    global _listener, _hook
    Atspi = atspi_focus.atspi()
    if Atspi is None or not IS_LINUX:
        return False
    _hook = hook

    def on_key(event):
        try:
            pressed = event.type == Atspi.EventType.KEY_PRESSED_EVENT
            vk, extended = vk_of(int(event.id))
            if not vk:
                return False
            flags = LLKHF_EXTENDED if extended else 0
            if not pressed:
                flags |= LLKHF_UP
            swallow = hook._process(vk, int(event.hw_code or 0), flags, pressed)
            if _TRACE:
                print(f"[TitanAccess] key: keysym=0x{int(event.id):x} {event.event_string!r} "
                      f"hw={event.hw_code} mods={event.modifiers} -> vk=0x{vk:x} ext={extended} "
                      f"{'down' if pressed else 'up'} swallow={bool(swallow)} "
                      f"readermod={getattr(hook, '_reader_mod', None)} ctrl={getattr(hook, '_ctrl', None)}",
                      flush=True)
            return bool(swallow)
        except Exception as e:                       # noqa: BLE001
            print(f"[TitanAccess] atspi_keys: {e}")
            return False

    try:
        _listener = Atspi.DeviceListener.new(on_key)
    except Exception as e:                           # noqa: BLE001
        print(f"[TitanAccess] atspi_keys: no device listener: {e}")
        return False
    S = Atspi.KeyListenerSyncType
    # SYNCHRONOUS so the application waits for the answer, CANCONSUME so
    # the answer may be "swallowed" - and deliberately NOT ALL_WINDOWS.
    # A global listener is served from an X keyboard grab, which a Wayland
    # session has not got and WSLg's XWayland refuses; a non-global one is
    # served by the application's own ATK bridge, which forwards every key
    # typed into a GTK, Qt or Chromium window to the registry BEFORE the
    # toolkit sees it (NotifyListenersSync) and drops the key when the
    # listener says so. Measured in WSLg: the grab is refused, the bridge
    # delivers. Registering both would deliver a key the reader did not
    # take twice - once from the grab, once from the bridge after the
    # replay. The binding insists on the enum, not an int.
    sync = S(int(S.SYNCHRONOUS) | int(S.CANCONSUME))
    types = 1 | 2                                    # pressed | released
    # One registration per modifier combination, as Orca does: a mask
    # covers only the keys pressed with exactly those modifiers.
    for mask in range(256):
        try:
            reply = Atspi.register_keystroke_listener(_listener, None, mask, types, sync)
        except Exception:                            # noqa: BLE001
            break
        _registered.append(mask)
        _replies['yes' if reply else 'no'] += 1
    if not _registered:
        print("[TitanAccess] atspi_keys: the accessibility bus took no "
              "registration; listening through pynput, without consuming")
        return _start_pynput(hook)
    if _replies['yes']:
        print(f"[TitanAccess] atspi_keys: listening on the accessibility bus "
              f"({len(_registered)} modifier masks)")
    else:
        # **The reply is advisory.** at-spi2-core up to 2.38 (Debian 11)
        # answers FALSE to every keystroke registration: the registry's
        # spi_controller_register_device_listener adds the listener, tells
        # every application about it, and then falls off the end of its
        # switch into ``return FALSE``. Measured here: 28 keys delivered
        # to a listener the bus had "refused". A registration that did
        # not raise is a registration; whether keys arrive is what the
        # hook's own counters say.
        print(f"[TitanAccess] atspi_keys: listening on the accessibility bus "
              f"({len(_registered)} modifier masks; the registry answered no "
              f"to each, which at-spi2-core 2.38 does for every one)")
    return True


def registration_report():
    """How many masks are registered and what the registry answered."""
    return {'masks': len(_registered), 'answered_yes': _replies['yes'],
            'answered_no': _replies['no'], 'pynput': _pynput_listener is not None}


_pynput_listener = None


def _start_pynput(hook):
    global _pynput_listener
    try:
        from pynput import keyboard
    except Exception as e:                           # noqa: BLE001
        print(f"[TitanAccess] atspi_keys: pynput unavailable: {e}")
        return False

    def keysym_of(key):
        try:
            vk = key.vk  # X keysym on the Xlib backend
            if vk is not None:
                return int(vk)
        except Exception:                            # noqa: BLE001
            pass
        char = getattr(key, 'char', None)
        return ord(char) if char else 0

    def feed(key, pressed):
        try:
            vk, extended = vk_of(keysym_of(key))
            if not vk:
                return
            flags = LLKHF_EXTENDED if extended else 0
            if not pressed:
                flags |= LLKHF_UP
            hook._process(vk, 0, flags, pressed)
        except Exception as e:                       # noqa: BLE001
            print(f"[TitanAccess] atspi_keys (pynput): {e}")

    try:
        _pynput_listener = keyboard.Listener(on_press=lambda k: feed(k, True),
                                             on_release=lambda k: feed(k, False))
        _pynput_listener.daemon = True
        _pynput_listener.start()
        return True
    except Exception as e:                           # noqa: BLE001
        print(f"[TitanAccess] atspi_keys: pynput listener failed: {e}")
        return False


def stop():
    global _listener, _hook
    Atspi = atspi_focus.atspi()
    if Atspi is None or _listener is None:
        return
    for mask in list(_registered):
        try:
            Atspi.deregister_keystroke_listener(_listener, None, mask, 1 | 2)
        except Exception:                            # noqa: BLE001
            pass
    _registered.clear()
    _listener = None
    _hook = None
    global _pynput_listener
    if _pynput_listener is not None:
        try:
            _pynput_listener.stop()
        except Exception:                            # noqa: BLE001
            pass
        _pynput_listener = None
