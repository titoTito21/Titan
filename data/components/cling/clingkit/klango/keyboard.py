# -*- coding: utf-8 -*-
"""The keyboard Klango's library polls, filled by whoever is driving Cling.

Klango does not receive keys, it **asks** for them, once per frame, in four
different shapes at once - and the shapes are not interchangeable, which is why
a queue of key names was never going to be enough:

- **the raw buffer** (`_Inp_KeySys_BuffGet`) is DirectInput: a *scan* code and
  whether it went down or up.  It is what tells left Shift from right Shift,
  and it is how a menu recognises Escape (`llib_suimenu.lua` looks for scan
  code 1 in `inp.keyboard`).
- **the held set** (`_Inp_KeySys_GetKeys`) is scan codes again, and the library
  counts frames off it - which is the whole difference between
  `k_KeyIsPressed` (held) and `k_KeyJustPressed` (held for exactly one frame).
- **the window messages** (`_Inp_KeySys_GetKeyMssages`) are Windows': a message
  type, a *virtual* key code, whether Control was down, and the character.
  This is the one the application shell reads, and it is where the menu comes
  from - `llib_suiapp.lua` opens it on message type 4 (WM_SYSKEYUP) with
  virtual key 18 (Alt).
- **the characters** (`_Inp_KeySys_GetChars` / `GetSysChars`) are what a text
  field types and what a menu's access letters match on.

So this module is one table - name, scan code, virtual key - and a queue that
answers all four from the same events.  Nothing here reads the real keyboard:
an application must not see keys pressed at anything other than its own window.
"""

import threading

#: Windows message types, as Klango's library reads them out of `k[1]`.
WM_KEYDOWN = 1
WM_KEYUP = 2
WM_SYSKEYDOWN = 3
WM_SYSKEYUP = 4
WM_CHAR = 5
WM_SYSCHAR = 6

#: name -> (DirectInput scan code, Windows virtual key code). The scan codes
#: are `k_KeyNames` in `llib_loop.lua`, read out of the library itself; the
#: virtual keys are Windows'. Both are needed and they are different numbers
#: for the same key, which is the trap this table exists to remove.
KEYS = {
    'escape': (1, 0x1B),
    'minus': (12, 0xBD), 'equals': (13, 0xBB),
    'backspace': (14, 0x08), 'tab': (15, 0x09),
    'leftbracket': (26, 0xDB), 'rightbracket': (27, 0xDD),
    'enter': (28, 0x0D),
    'lctrl': (29, 0x11), 'rctrl': (157, 0x11),
    'semicolon': (39, 0xBA), 'apostrophe': (40, 0xDE), 'grave': (41, 0xC0),
    'lshift': (42, 0x10), 'rshift': (54, 0x10), 'backslash': (43, 0xDC),
    'comma': (51, 0xBC), 'period': (52, 0xBE), 'slash': (53, 0xBF),
    'multiply': (55, 0x6A),
    'lalt': (56, 0x12), 'ralt': (184, 0x12),
    'space': (57, 0x20), 'capslock': (58, 0x14),
    'numlock': (69, 0x90), 'scrolllock': (70, 0x91),
    'subtract': (74, 0x6D), 'add': (78, 0x6B), 'decimal': (83, 0x6E),
    'divide': (181, 0x6F),
    'pause': (197, 0x13),
    'home': (199, 0x24), 'up': (200, 0x26), 'pageup': (201, 0x21),
    'left': (203, 0x25), 'right': (205, 0x27), 'end': (207, 0x23),
    'down': (208, 0x28), 'pagedown': (209, 0x22),
    'insert': (210, 0x2D), 'delete': (211, 0x2E),
    'lwin': (219, 0x5B), 'rwin': (220, 0x5C), 'apps': (221, 0x5D),
}

for _index, _letter in enumerate('qwertyuiop'):
    KEYS[_letter] = (16 + _index, ord(_letter.upper()))
for _index, _letter in enumerate('asdfghjkl'):
    KEYS[_letter] = (30 + _index, ord(_letter.upper()))
for _index, _letter in enumerate('zxcvbnm'):
    KEYS[_letter] = (44 + _index, ord(_letter.upper()))
for _index, _digit in enumerate('1234567890'):
    KEYS[_digit] = (2 + _index, ord(_digit))
for _index in range(1, 11):                                    # F1 .. F10
    KEYS['f%d' % _index] = (58 + _index, 0x6F + _index)
KEYS['f11'] = (87, 0x7A)
KEYS['f12'] = (88, 0x7B)
for _index, _scan in enumerate((82, 79, 80, 81, 75, 76, 77, 71, 72, 73)):
    KEYS['numpad%d' % _index] = (_scan, 0x60 + _index)

#: What Cling's own windows and engines call a key, in Klango's words. The
#: names on the left are the ones `ui.py` produces and the ones an action or a
#: test would naturally use.
ALIASES = {
    'esc': 'escape', 'return': 'enter', 'lenter': 'enter', 'renter': 'enter',
    'prior': 'pageup', 'next': 'pagedown', 'back': 'backspace',
    'del': 'delete', 'ins': 'insert',
    'ctrl': 'lctrl', 'control': 'lctrl', 'alt': 'lalt', 'menu': 'lalt',
    'shift': 'lshift', 'win': 'lwin', 'spacebar': 'space',
    ' ': 'space', '-': 'minus', '=': 'equals', '[': 'leftbracket',
    ']': 'rightbracket', ';': 'semicolon', "'": 'apostrophe', '`': 'grave',
    '\\': 'backslash', ',': 'comma', '.': 'period', '/': 'slash',
}

#: The character a key types, when it types one and its name is not already it.
CHARACTERS = {
    'space': ' ', 'minus': '-', 'equals': '=', 'leftbracket': '[',
    'rightbracket': ']', 'semicolon': ';', 'apostrophe': "'", 'grave': '`',
    'backslash': '\\', 'comma': ',', 'period': '.', 'slash': '/',
    'multiply': '*', 'add': '+', 'subtract': '-', 'divide': '/',
    'decimal': '.', 'enter': '\r', 'tab': '\t',
}
for _index in range(10):
    CHARACTERS['numpad%d' % _index] = str(_index)

#: The three keys that are modifiers rather than input, by canonical name.
MODIFIERS = {'lshift': 'shift', 'rshift': 'shift', 'lctrl': 'ctrl',
             'rctrl': 'ctrl', 'lalt': 'alt', 'ralt': 'alt'}


def canonical(name):
    """The canonical name of a key, or '' when it is not one Klango knows.

    **A key may be its own character, and one of those characters is a
    space.** Trimming the name first is right for `" enter "` and wrong for
    `" "` - it leaves nothing at all - so the space bar was not a key Cling
    recognised, and `press(' ')` answered False and typed nothing. Nothing
    about that is visible: an application takes every other letter, so a
    search box is filled in, reads back as what was typed (the library
    speaks a space as a SOUND, not a word) and is one word where the typist
    wrote two. It is why the Wikipedia browser answered "I could not find
    anything matching your query" to a title that is on the front page, and
    it is the same in every chat, note and name field there is.
    """
    text = str(name or '')
    if not text:
        return ''
    # The trim is for a name with room around it; a name that IS whitespace
    # keeps itself, so ' ' can still reach the alias table.
    lowered = text.strip().lower() or text.lower()
    lowered = ALIASES.get(lowered, lowered)
    return lowered if lowered in KEYS else ''


class Keyboard(object):
    """One frame of keyboard, and a queue of the frames still to be delivered.

    The driver - a window, an engine, a test - calls `press`, `down` and `up`
    on whatever thread it likes; the application's own thread takes a frame at
    `refresh()`, which is the first thing Klango's `_k_CheckRawInput` does. In
    between, the queue is the only shared state and it is behind a lock, so a
    key pressed while the interpreter is mid-frame is delivered whole at the
    start of the next one rather than half-seen in this one.
    """

    def __init__(self):
        self._lock = threading.Lock()
        #: Events waiting for a frame: (canonical name, is_down, character).
        self._pending = []
        #: Keys whose release is owed after the frame their press was in. A
        #: window that only ever says "this key was pressed" still produces a
        #: key that goes down and comes up, which is what `k_KeyJustPressed`
        #: (held for exactly one frame) is asking about.
        self._release_after = []
        #: Scan codes held right now.
        self.held = set()
        #: Every scan code this keyboard has ever touched. DirectInput hands
        #: Klango the state of the WHOLE keyboard, so `_k_CheckRawInput` is
        #: told about a key that is not held as well as one that is - and it
        #: needs to be: that is the only place it clears its own
        #: `_rawkeypressed` count. Reporting held keys alone left the count
        #: standing at 1, so the SECOND press of a key counted 2 and
        #: `k_KeyJustPressed` - which is `== 1` - was false for ever after.
        #: Measured: Enter chose a menu item once and then never again.
        self.touched = set()
        #: This frame, in the four shapes the library reads.
        self.buffer = []          # (scan code, 1 down / 0 up)
        self.messages = []        # (type, virtual key, ctrl, char, 0)
        self.chars = []
        self.syschars = []
        self.wmdown = []
        self.wmup = []
        self.wmsysdown = []
        self.wmsysup = []

    # ------------------------------------------------------------- filling
    def press(self, name, character=None):
        """A key that goes down now and comes up at the end of its frame."""
        found = canonical(name)
        if not found:
            # Anything that is not a key by name may still be a character -
            # a typing course is given what was typed, not what was pressed.
            text = str(name or '')
            if len(text) == 1:
                found = canonical(text)
            if not found:
                return False
        self.down(found, character)
        with self._lock:
            self._release_after.append(found)
        return True

    def down(self, name, character=None):
        found = canonical(name)
        if not found:
            return False
        with self._lock:
            self._pending.append((found, True, character))
        return True

    def up(self, name):
        found = canonical(name)
        if not found:
            return False
        with self._lock:
            self._pending.append((found, False, None))
        return True

    def clear(self):
        """Let go of everything. Used when the window loses the keyboard."""
        with self._lock:
            for name, (scan, _vk) in KEYS.items():
                if scan in self.held:
                    self._pending.append((name, False, None))
            self._release_after = []

    # -------------------------------------------------------------- frames
    def refresh(self):
        """Take the next frame of input. Klango calls this once per frame."""
        with self._lock:
            events = self._pending
            self._pending = [(name, False, None)
                             for name in self._release_after]
            self._release_after = []
        self.buffer = []
        self.messages = []
        self.chars = []
        self.syschars = []
        self.wmdown = []
        self.wmup = []
        self.wmsysdown = []
        self.wmsysup = []
        for name, is_down, character in events:
            self._apply(name, is_down, character)
        return True

    def states(self):
        """`_Inp_KeySys_GetKeys` - scan code -> 1 held, 0 not.

        Every key that has been touched is reported, not only the ones down
        now; see `touched`.
        """
        out = {}
        for scan in self.touched:
            out[scan] = 1 if scan in self.held else 0
        return out

    def _apply(self, name, is_down, character):
        scan, virtual = KEYS[name]
        self.touched.add(scan)
        if is_down:
            self.held.add(scan)
        else:
            self.held.discard(scan)
        self.buffer.append((scan, 1 if is_down else 0))

        # Alt held makes a key press a SYS message, which is how Windows says
        # "this belongs to the window, not to what is typed in it" - and it is
        # the only difference between typing a letter and reaching a menu.
        with_alt = self._alt_held() or name in ('lalt', 'ralt')
        control = 1 if self._ctrl_held() else 0
        text = character if character is not None else CHARACTERS.get(name, '')
        if not text and len(name) == 1:
            text = name
        if is_down:
            kind = WM_SYSKEYDOWN if with_alt else WM_KEYDOWN
            (self.wmsysdown if with_alt else self.wmdown).append(virtual)
        else:
            kind = WM_SYSKEYUP if with_alt else WM_KEYUP
            (self.wmsysup if with_alt else self.wmup).append(virtual)
        self.messages.append((kind, virtual, control, text, 0))

        # A character message follows its key down, as Windows' own
        # TranslateMessage produces it - and only for a key that types
        # something and no Control held, because Ctrl+A is a command.
        if is_down and text and text not in ('\r', '\t') and not control:
            if with_alt and name not in ('lalt', 'ralt'):
                self.syschars.append(text)
                self.messages.append((WM_SYSCHAR, virtual, control, text, 0))
            elif not with_alt:
                self.chars.append(text)
                self.messages.append((WM_CHAR, virtual, control, text, 0))

    def _alt_held(self):
        return KEYS['lalt'][0] in self.held or KEYS['ralt'][0] in self.held

    def _ctrl_held(self):
        return KEYS['lctrl'][0] in self.held or KEYS['rctrl'][0] in self.held

    def shift_held(self):
        return KEYS['lshift'][0] in self.held or KEYS['rshift'][0] in self.held

    def control_held(self):
        return self._ctrl_held()

    def alt_held(self):
        return self._alt_held()

    # ------------------------------------------------------------- reading
    def count(self):
        return len(self.buffer)

    def at(self, index):
        """`_Inp_KeySys_BuffGet(i)` - scan code and direction, indexed from 0."""
        try:
            position = int(index or 0)
        except (TypeError, ValueError):
            position = 0
        if 0 <= position < len(self.buffer):
            return self.buffer[position]
        return (0, 0)
