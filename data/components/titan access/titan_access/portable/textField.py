# -*- coding: utf-8 -*-
"""A field's own text, as something to walk - and to type into.

**The edit field IS a virtual window.** Handing the keys to whatever
happens to be focused is what this replaced, and it was wrong in two
ways: over a row read off a picture there is nothing focused to receive
them at all, and even over a real control the reader is then guessing
what the control did with each key rather than knowing.

So the field's text becomes the thing the cursor walks, exactly as a
window's controls do:

* **Up and Down are lines**, and the line is said.
* **Left and Right are characters**, and the character is said - which is
  how somebody proof-reads a word by ear.
* **Control with them is words**, Home and End are the ends of the line,
  and Control with those are the ends of the text.
* **A letter, a digit or a space is typed in** at the caret, and is
  echoed. **Backspace** takes the character before it and says the one
  that went, which is what tells somebody they deleted the right one.

Everything here is arithmetic on a string: no NVDA, no Titan, no window.
That is what lets the same file answer for a real control, for a row read
off a virtual machine's screen, and for a field in a described
application - and be tested without any of them.
"""

import threading

from . import i18n

_ = i18n.install(globals())

_LOCK = threading.RLock()

_counted = {'made': 0, 'typed': 0, 'deleted': 0, 'moved': 0}


def report():
    with _LOCK:
        return dict(_counted)


def forget():
    with _LOCK:
        for key in _counted:
            _counted[key] = 0


def _text(value):
    return '' if value is None else str(value)


class Field(object):
    """One field's text and where the caret is in it."""

    __slots__ = ('text', 'at', 'multiline', 'readonly')

    def __init__(self, text='', at=None, multiline=False, readonly=False):
        self.text = _text(text)
        self.at = len(self.text) if at is None else self._clamp(at)
        self.multiline = bool(multiline)
        self.readonly = bool(readonly)
        with _LOCK:
            _counted['made'] += 1

    # ------------------------------------------------------------- where
    def _clamp(self, at):
        try:
            return max(0, min(int(at), len(self.text)))
        except Exception:                            # noqa: BLE001
            return 0

    @property
    def lines(self):
        return self.text.split('\n')

    @property
    def line(self):
        """Which line the caret is on, from 0."""
        return self.text.count('\n', 0, self.at)

    @property
    def column(self):
        start = self.text.rfind('\n', 0, self.at) + 1
        return self.at - start

    def line_text(self, index=None):
        rows = self.lines
        index = self.line if index is None else index
        return rows[index] if 0 <= index < len(rows) else ''

    def character(self):
        """The character the caret is ON, which is the one to the right.

        A caret sits BETWEEN characters, and every reader says the one
        after it - that is what Right then says next, so saying the one
        before would announce a different character from the one the next
        keystroke acts on.
        """
        return self.text[self.at] if self.at < len(self.text) else ''

    # ------------------------------------------------------------ moving
    def left(self, by_word=False):
        was = self.at
        self.at = self._word_edge(-1) if by_word else max(0, self.at - 1)
        return self._moved(was)

    def right(self, by_word=False):
        was = self.at
        self.at = self._word_edge(1) if by_word \
            else min(len(self.text), self.at + 1)
        return self._moved(was)

    def up(self, count=1):
        return self._line(-count)

    def down(self, count=1):
        return self._line(count)

    def home(self, whole=False):
        was = self.at
        self.at = 0 if whole else self.text.rfind('\n', 0, self.at) + 1
        return self._moved(was)

    def end(self, whole=False):
        was = self.at
        if whole:
            self.at = len(self.text)
        else:
            found = self.text.find('\n', self.at)
            self.at = len(self.text) if found < 0 else found
        return self._moved(was)

    def _line(self, direction):
        """Up or down, keeping the column - which is what a caret does."""
        rows = self.lines
        wanted = self.line + direction
        if wanted < 0 or wanted >= len(rows):
            return False
        column = min(self.column, len(rows[wanted]))
        self.at = sum(len(one) + 1 for one in rows[:wanted]) + column
        with _LOCK:
            _counted['moved'] += 1
        return True

    def _word_edge(self, direction):
        at = self.at
        if direction < 0:
            while at > 0 and self.text[at - 1].isspace():
                at -= 1
            while at > 0 and not self.text[at - 1].isspace():
                at -= 1
            return at
        end = len(self.text)
        while at < end and not self.text[at].isspace():
            at += 1
        while at < end and self.text[at].isspace():
            at += 1
        return at

    def _moved(self, was):
        if self.at == was:
            return False
        with _LOCK:
            _counted['moved'] += 1
        return True

    # ------------------------------------------------------------ typing
    def insert(self, piece):
        """Put text in at the caret. ``(ok, what went in)``."""
        piece = _text(piece)
        if self.readonly or not piece:
            return False, ''
        self.text = self.text[:self.at] + piece + self.text[self.at:]
        self.at += len(piece)
        with _LOCK:
            _counted['typed'] += len(piece)
        return True, piece

    def backspace(self, by_word=False):
        """Take what is before the caret. ``(ok, what went)``."""
        if self.readonly or self.at <= 0:
            return False, ''
        start = self._word_edge(-1) if by_word else self.at - 1
        gone = self.text[start:self.at]
        self.text = self.text[:start] + self.text[self.at:]
        self.at = start
        with _LOCK:
            _counted['deleted'] += len(gone)
        return True, gone

    def delete(self, by_word=False):
        """Take what is after the caret. ``(ok, what went)``."""
        if self.readonly or self.at >= len(self.text):
            return False, ''
        end = self._word_edge(1) if by_word else self.at + 1
        gone = self.text[self.at:end]
        self.text = self.text[:self.at] + self.text[end:]
        with _LOCK:
            _counted['deleted'] += len(gone)
        return True, gone

    # ------------------------------------------------------------ saying
    def parts(self):
        """``[(text, voice class)]`` for where the caret now is.

        The line, and where in the field it is - the same shape every
        other list in this reader is announced in, because a field walked
        this way IS one.
        """
        rows = self.lines
        said = self.line_text()
        found = [(said if said else _('blank'), 'name')]
        if len(rows) > 1:
            found.append((_('{at} of {count}').format(at=self.line + 1,
                                                      count=len(rows)),
                          'place'))
        return found


#: What one key does to a field.
MOVES = ('left', 'right', 'up', 'down', 'home', 'end',
         'pageup', 'pagedown')

#: **The same key, spelled three ways.** NVDA says `leftArrow` and
#: `control`; the wire that reaches a described application says `left`
#: and `ctrl`; a person writing a caller says whichever they think of.
#: A key that is not recognised is handed back to the program - which is
#: right for Tab and catastrophic for an arrow, because the arrow then
#: reaches the real control and the classic edit field answers it
#: underneath the one being walked. So every spelling is known here, in
#: the one place that decides what a key means.
SPELLINGS = {
    'leftarrow': 'left', 'rightarrow': 'right',
    'uparrow': 'up', 'downarrow': 'down',
    'backspace': 'back', 'return': 'enter',
    'page up': 'pageup', 'page down': 'pagedown',
    'prior': 'pageup', 'next': 'pagedown',
    'escape': 'escape',
}

#: The modifier names, likewise: NVDA's `control`, everybody else's
#: `ctrl`.
BY_WORD = ('ctrl+', 'control+')


def bare_name(key):
    """The key's own name, in this module's spelling."""
    bare = str(key or '').rsplit('+', 1)[-1]
    return SPELLINGS.get(bare.lower(), bare.lower())


def held(key):
    """``(by_word, shift)`` out of whatever modifiers were named."""
    name = str(key or '').lower()
    return (any(one in name for one in BY_WORD), 'shift+' in name)


def press(field, key):
    """One key against a field. ``(what happened, what to say)``.

    ``what happened`` is ``'moved'``, ``'typed'``, ``'deleted'``,
    ``'edge'`` (it would not go) or ``''`` (not ours, so the caller
    should pass it on). One place decides, so the two readers and the two
    modes cannot drift apart about what Backspace means.
    """
    name = _text(key)
    bare = bare_name(name)
    by_word, shift = held(name)

    if bare in MOVES:
        if bare == 'left':
            went = field.left(by_word)
        elif bare == 'right':
            went = field.right(by_word)
        elif bare == 'up':
            went = field.up()
        elif bare == 'down':
            went = field.down()
        elif bare in ('pageup', 'pagedown'):
            went = field.up(10) if bare == 'pageup' else field.down(10)
        elif bare == 'home':
            went = field.home(whole=by_word)
        else:
            went = field.end(whole=by_word)
        if not went:
            return 'edge', ''
        # Along a line the character is the news; across lines the line
        # is. Saying the whole line for every Left would bury the letter
        # somebody is checking.
        if bare in ('left', 'right') and not by_word:
            return 'moved', field.character() or _('end')
        return 'moved', field.line_text() or _('blank')

    if bare in ('back', 'backspace'):
        ok, gone = field.backspace(by_word)
        return ('deleted', gone) if ok else ('edge', '')
    if bare == 'delete':
        ok, gone = field.delete(by_word)
        return ('deleted', gone) if ok else ('edge', '')
    if bare in ('return', 'enter'):
        if not field.multiline:
            # In a one-line field Enter belongs to the FORM - it is what
            # presses the default button - so it is handed back.
            return '', ''
        ok, _piece = field.insert('\n')
        return ('typed', _('new line')) if ok else ('edge', '')
    if bare == 'space':
        ok, _piece = field.insert(' ')
        return ('typed', _('space')) if ok else ('edge', '')
    if bare == 'tab':
        return '', ''
    if bare == 'escape':
        # The way out, and never typed.
        return '', ''
    if len(bare) == 1 and not by_word:
        piece = name.rsplit('+', 1)[-1]
        # A reader sends `shift+n`; a caller may send the character it
        # means. Either gives a capital.
        piece = piece.upper() if (shift or piece.isupper()) else bare
        ok, put = field.insert(piece)
        return ('typed', put) if ok else ('edge', '')
    return '', ''
