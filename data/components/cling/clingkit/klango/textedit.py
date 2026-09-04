# -*- coding: utf-8 -*-
"""`_Gfx_TxtEdit_*` - the control a Klango application is typed into.

It is the one part of Klango's graphics that is not decoration. Everything
else `_Gfx_` does is drawing, and a Cling application is heard rather than
seen, so the whole family answers and paints nothing - but the text control is
where a search term, a message, a note or a name is written, and an emulator
that has not got one stops the moment an application asks for one:
`attempt to call a nil value '_Gfx_TxtEdit_Init'`, which is where the
Wikipedia browser, the chat and every application with a field ended.

Klango's own is a Windows rich edit. It has the keyboard, so it edits itself
and the application is only TOLD what was typed (`txted:processchar` speaks
the character; it never inserts it). Cling has no such control, so this is the
buffer - a string, a caret, a selection - and `apply()` is what the keyboard
does to it each frame, in the same place Windows would have done it.

Two details are Klango's and not negotiable:

* **a line ends with `\\r`**, not `\\n`. `llib_suitexted2.lua` finds the next
  line with `_Gfx_TxtEdit_Find(self.richedit, "\\r", ...)`, so a buffer that
  used `\\n` would be one line however much was typed into it.
* **a position is a PAIR**. `_Gfx_TxtEdit_GetCurrentPos` answers the start and
  the end of the selection, and the library reads `sel[2]-sel[1]` to find out
  whether anything is selected at all.
"""

#: What `_Gfx_TxtEdit_GetText(handle, mode)` is being asked for. The numbers
#: are `llib_suitexted2.lua`'s own (`___char`, `___word`, ...).
CHAR = 0
WORD = 1
SENTENCE = 2
PARAGRAPH = 3
ALL = 4
PARAGRAPH_ALL = 5
FROM_LINE = 11
FROM_CARET = 12
WORD_BACKWARD = 13
FROM_CARET_RANGE = 14

#: Klango's line separator, and the one the library searches for.
NEWLINE = '\r'

#: Where a sentence ends, for `GetText(SENTENCE)`.
SENTENCE_ENDS = '.!?'

#: The virtual keys the control acts on itself. Everything else is the
#: application's.
VK_BACK, VK_TAB, VK_RETURN = 0x08, 0x09, 0x0D
VK_END, VK_HOME, VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN = (0x23, 0x24, 0x25,
                                                      0x26, 0x27, 0x28)
VK_DELETE = 0x2E


def _is_word(character):
    return character.isalnum() or character == '_'


def as_lines(text):
    """Text with Klango's own line separator in it.

    A rich edit stores a paragraph break as `\\r` and normalises whatever it
    is given, so everything Klango's library then does about lines - `Find`
    for the next one, `GetCurrentLine`, `GetNumberOfLines`, the Up and Down
    arrows - is `\\r` and nothing else. A document put in with `\\n` is
    therefore ONE line however long it is: the Wikipedia browser's article
    view read its first paragraph, buzzed at both ends and never moved,
    because as far as the control was concerned there was nowhere to go.
    """
    return str(text or '').replace('\r\n', '\n').replace('\n', NEWLINE)


class TextEdit(object):
    """One text control: a string, a caret, and a selection."""

    def __init__(self, identifier, multiline=False, readonly=False,
                 password=False, maxlen=-1, fontsize=12, rich=False):
        self.id = identifier
        self.multiline = bool(multiline)
        self.readonly = bool(readonly)
        self.password = bool(password)
        self.rich = bool(rich)
        self.fontsize = int(fontsize or 12)
        self.limit = int(maxlen) if maxlen not in (None, '') else -1
        self.text = ''
        self.caret = 0
        #: Where a selection started. Equal to the caret when nothing is
        #: selected, which is what the library reads it as.
        self.mark = 0
        self.focused = False
        self.blocked = False
        #: The character the last backspace removed - `GetDelZnak`, which the
        #: library speaks so the typist hears what they took out.
        self.deleted = ''
        self.destroyed = False

    # ------------------------------------------------------------ position
    @property
    def selection(self):
        return (min(self.caret, self.mark), max(self.caret, self.mark))

    def set_caret(self, position, extend=False):
        position = max(0, min(len(self.text), int(position)))
        self.caret = position
        if not extend:
            self.mark = position

    def set_range(self, start, end=None):
        if end is None:
            self.set_caret(start)
            return
        start = max(0, min(len(self.text), int(start)))
        end = max(0, min(len(self.text), int(end)))
        self.mark, self.caret = start, end

    # -------------------------------------------------------------- typing
    def set_text(self, text):
        """Replace the whole document - `SetText`, `SetText2`, `LoadFile`."""
        self.text = as_lines(text)
        self.set_caret(0)
        return True

    def insert(self, text):
        """Type something. Refused on a read-only control, and capped."""
        if self.readonly or self.blocked or not text:
            return False
        self.delete_selection()
        text = as_lines(text)
        if self.limit is not None and self.limit >= 0:
            room = self.limit - len(self.text)
            if room <= 0:
                return False
            text = text[:room]
        self.text = self.text[:self.caret] + text + self.text[self.caret:]
        self.set_caret(self.caret + len(text))
        return True

    def delete_selection(self):
        start, end = self.selection
        if start == end:
            return False
        self.text = self.text[:start] + self.text[end:]
        self.set_caret(start)
        return True

    def backspace(self):
        if self.readonly or self.blocked:
            return False
        if self.delete_selection():
            return True
        if self.caret <= 0:
            return False
        self.deleted = self.text[self.caret - 1]
        self.text = self.text[:self.caret - 1] + self.text[self.caret:]
        self.set_caret(self.caret - 1)
        return True

    def delete(self):
        if self.readonly or self.blocked:
            return False
        if self.delete_selection():
            return True
        if self.caret >= len(self.text):
            return False
        self.deleted = self.text[self.caret]
        self.text = self.text[:self.caret] + self.text[self.caret + 1:]
        return True

    def replace_selection(self, text):
        if self.readonly or self.blocked:
            return False
        self.delete_selection()
        return self.insert(str(text or ''))

    # ------------------------------------------------------------- reading
    def line_bounds(self, position=None):
        """Where the line holding `position` starts and ends."""
        position = self.caret if position is None else position
        position = max(0, min(len(self.text), int(position)))
        start = self.text.rfind(NEWLINE, 0, position) + 1
        end = self.text.find(NEWLINE, position)
        return start, len(self.text) if end < 0 else end

    def word_bounds(self, position=None, backward=False):
        position = self.caret if position is None else position
        text = self.text
        if backward and position > 0:
            position -= 1
        if not text:
            return 0, 0
        position = max(0, min(len(text) - 1, position))
        if not _is_word(text[position]):
            # Standing on a space: the word that has just been finished is
            # the one a typist means.
            while position > 0 and not _is_word(text[position - 1]):
                position -= 1
            if position == 0:
                return 0, 0
            position -= 1
        start = position
        while start > 0 and _is_word(text[start - 1]):
            start -= 1
        end = position
        while end < len(text) and _is_word(text[end]):
            end += 1
        return start, end

    def sentence_bounds(self, position=None):
        position = self.caret if position is None else position
        text = self.text
        start = 0
        for index in range(min(position, len(text)) - 1, -1, -1):
            if text[index] in SENTENCE_ENDS or text[index] == NEWLINE:
                start = index + 1
                break
        end = len(text)
        for index in range(min(position, len(text)), len(text)):
            if text[index] in SENTENCE_ENDS:
                end = index + 1
                break
            if text[index] == NEWLINE:
                end = index
                break
        return start, min(end, len(text))

    def get_text(self, mode=ALL):
        """What the library is asking to be read out - see the mode table."""
        try:
            mode = int(mode)
        except (TypeError, ValueError):
            mode = ALL
        if mode == ALL:
            return self.text
        if mode == CHAR:
            return self.text[self.caret:self.caret + 1]
        if mode == WORD:
            start, end = self.word_bounds()
            return self.text[start:end]
        if mode == WORD_BACKWARD:
            start, end = self.word_bounds(backward=True)
            return self.text[start:end]
        if mode == SENTENCE:
            start, end = self.sentence_bounds()
            return self.text[start:end]
        if mode in (PARAGRAPH, PARAGRAPH_ALL):
            start, end = self.line_bounds()
            return self.text[start:end]
        if mode == FROM_LINE:
            start, _end = self.line_bounds()
            return self.text[start:]
        if mode in (FROM_CARET, FROM_CARET_RANGE):
            return self.text[self.caret:]
        return self.text

    def current_line(self, position=None, from_caret=False):
        start, end = self.line_bounds(position)
        if from_caret:
            start = max(start, self.caret if position is None else position)
        return self.text[start:end]

    def text_range(self, start, end):
        start = max(0, min(len(self.text), int(start or 0)))
        end = max(0, min(len(self.text), int(end or 0)))
        if end < start:
            start, end = end, start
        return self.text[start:end]

    def lines(self):
        return self.text.count(NEWLINE) + 1

    def line_index(self, position=None):
        """Which line `position` is on, counted from ZERO.

        It is the second thing `_Gfx_TxtEdit_GetCurrentLine` answers, and the
        library turns on it: a textarea reads it on every Up and Down to find
        out whether the caret is on the first line or the last one, and buzzes
        when it is (`llib_suitexted2.lua`). Answering only the line's TEXT
        left it nil, so a multiline field never said it had reached its top or
        its bottom - the arrows moved and nothing ever told the reader they
        had stopped moving.
        """
        position = self.caret if position is None else position
        position = max(0, min(len(self.text), int(position)))
        return self.text.count(NEWLINE, 0, position)

    def find(self, needle, start=None, forward=True):
        """Where `needle` is, or None. `start` is where to look from."""
        needle = str(needle or '')
        if not needle:
            return None
        if forward:
            begin = self.caret if start is None else int(start)
            found = self.text.find(needle, max(0, begin))
        else:
            begin = self.caret if start is None else int(start)
            found = self.text.rfind(needle, 0, max(0, begin))
        return None if found < 0 else found

    def at_end_of_line(self):
        _start, end = self.line_bounds()
        return self.caret >= end

    # -------------------------------------------------------- the keyboard
    def key(self, virtual, shift=False, control=False):
        """One key, as the control itself would have taken it.

        True when the control used it. The application is told about the key
        either way - Klango's own control has the keyboard and the
        application still sees the message - so this only decides what
        happens to the TEXT.
        """
        if self.blocked:
            return False
        if virtual == VK_LEFT:
            self._step(-1, shift, control)
        elif virtual == VK_RIGHT:
            self._step(1, shift, control)
        elif virtual == VK_HOME:
            start, _end = self.line_bounds()
            self.set_caret(0 if control else start, shift)
        elif virtual == VK_END:
            _start, end = self.line_bounds()
            self.set_caret(len(self.text) if control else end, shift)
        elif virtual in (VK_UP, VK_DOWN) and self.multiline:
            self._line_step(-1 if virtual == VK_UP else 1, shift)
        elif virtual == VK_BACK:
            return self.backspace()
        elif virtual == VK_DELETE:
            return self.delete()
        elif virtual == VK_RETURN and self.multiline:
            return self.insert(NEWLINE)
        else:
            return False
        return True

    def _step(self, direction, shift, control):
        if control:
            start, end = self.word_bounds(backward=direction < 0)
            self.set_caret(start if direction < 0 else end, shift)
            return
        self.set_caret(self.caret + direction, shift)

    def _line_step(self, direction, shift):
        start, end = self.line_bounds()
        column = self.caret - start
        if direction < 0:
            if start <= 0:
                return
            above_start, above_end = self.line_bounds(start - 1)
            self.set_caret(min(above_start + column, above_end), shift)
        else:
            if end >= len(self.text):
                return
            below_start, below_end = self.line_bounds(end + 1)
            self.set_caret(min(below_start + column, below_end), shift)


class Editors(object):
    """Every text control an application has made, and which one has focus."""

    def __init__(self):
        self.by_id = {}
        self.focused = None
        self._next = 0

    def create(self, **options):
        self._next += 1
        editor = TextEdit(self._next, **options)
        self.by_id[self._next] = editor
        if self.focused is None:
            self.focused = editor
        return editor

    def get(self, handle):
        if isinstance(handle, TextEdit):
            return handle
        try:
            return self.by_id.get(int(handle))
        except (TypeError, ValueError):
            return None

    def destroy(self, handle):
        editor = self.get(handle)
        if editor is None:
            return False
        editor.destroyed = True
        self.by_id.pop(editor.id, None)
        if self.focused is editor:
            self.focused = None
        return True

    def focus(self, handle, take=True):
        """`_Gfx_TxtEdit_SetFocus(handle, f)` - and `f` is not decoration.

        1 is "this control has the keyboard now" and **0 is "it has given it
        up"**: the library says 0 the moment a control is created and again
        when the user leaves it (`llib_suitexted2.lua` does both, and
        `llib_suigfx.lua` remembers `HasFocus` across a dialog so it can put
        it back). Reading the handle and ignoring the flag meant every one of
        those gave the keyboard TO the control instead of taking it away, so
        the control being typed into was whichever one had most recently been
        built or left - and the arrows, the letters and the backspace all
        went to a buffer nobody was looking at.
        """
        editor = self.get(handle)
        if editor is None:
            return False
        if not take:
            editor.focused = False
            if self.focused is editor:
                self.focused = None
            return True
        for other in self.by_id.values():
            other.focused = other is editor
        self.focused = editor
        return True

    def apply(self, keyboard):
        """Let the focused control take this frame's typing.

        Called from `_Inp_KeySys_Refresh`, which is where Klango's own frame
        reads the keyboard - and in Klango the control has already had the
        keys by then, because Windows gave them to it.
        """
        editor = self.focused
        if editor is None or editor.destroyed or editor.blocked:
            return False
        shift = keyboard.shift_held()
        control = keyboard.control_held()
        used = False
        for virtual in keyboard.wmdown:
            if editor.key(virtual, shift, control):
                used = True
        if not control:
            for character in keyboard.chars:
                if character and character >= ' ':
                    used = editor.insert(character) or used
        return used
