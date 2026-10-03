# -*- coding: utf-8 -*-
"""Editable-text review for Titan Access.

Python port of the C# ``EditableText/EditableTextHandler.cs`` (itself a port of
NVDA's ``editableText.py``). Reads and navigates the text of the focused edit /
document control through the UI Automation ``TextPattern`` exposed by
``engine.current_object.native`` (a vendored ``uiautomation.Control``).

A small review cursor is maintained as a degenerate ``TextRange`` that starts at
the caret (the current text selection) and is moved by character / word / line
units. Whenever the focused object changes, the review cursor is re-seeded from
the live caret so reading always starts where the user is.

Single characters are spoken through
:func:`titan_access.localization.character_announcement` (honouring
``settings.phonetic_letters``); words and lines are spoken verbatim. When the
control exposes no ``TextPattern`` every method announces ``edit.cannotNavigate``.
"""

import os
import sys
import time

from titan_access.localization import L, character_announcement

# Opt-in console tracing of caret navigation (set the env var before launching
# TCE / the reader). Prints what each arrow read sees, to diagnose "it reads the
# old line" reports on a real machine where caret tracking can't be reproduced
# in a test sandbox.
_DEBUG_CARET = bool(os.environ.get("TITAN_ACCESS_DEBUG"))

try:  # vendored uiautomation lib
    import uiautomation as _auto
    _TEXT_PATTERN_ID = _auto.PatternId.TextPattern
    _UNIT_CHAR = _auto.TextUnit.Character
    _UNIT_WORD = _auto.TextUnit.Word
    _UNIT_LINE = _auto.TextUnit.Line
    _EP_START = _auto.TextPatternRangeEndpoint.Start
    _EP_END = _auto.TextPatternRangeEndpoint.End
except Exception as e:  # pragma: no cover - degrades to "cannot navigate"
    print(f"[TitanAccess] editable_text: uiautomation unavailable: {e}")
    _auto = None
    _TEXT_PATTERN_ID = _UNIT_CHAR = _UNIT_WORD = _UNIT_LINE = None
    _EP_START = _EP_END = None


# --------------------------------------------------------------------------- #
# Win32 edit-control fallback (no UIA TextPattern needed)
# --------------------------------------------------------------------------- #
# Many edit controls expose NO UIA TextPattern at all -- the classic Win32 EDIT,
# and wx.TextCtrl (which wraps it), among others. For those, caret tracking via
# TextPattern reads nothing, so arrows are silent. We fall back to plain Win32
# messages (EM_GETSEL for the caret offset, WM_GETTEXT for the buffer) and slice
# the line / word / char out ourselves, mirroring how NVDA reads legacy edits.
import re as _re

if os.name == "nt":
    import ctypes as _ctypes
    from ctypes import wintypes as _wt

    _WM_GETTEXT = 0x000D
    _WM_GETTEXTLENGTH = 0x000E
    _EM_GETSEL = 0x00B0

    class _GUITHREADINFO(_ctypes.Structure):
        _fields_ = [
            ("cbSize", _wt.DWORD), ("flags", _wt.DWORD),
            ("hwndActive", _wt.HWND), ("hwndFocus", _wt.HWND),
            ("hwndCapture", _wt.HWND), ("hwndMenuOwner", _wt.HWND),
            ("hwndMoveSize", _wt.HWND), ("hwndCaret", _wt.HWND),
            ("rcCaret", _wt.RECT),
        ]

    # Fully-typed user32 (restype/argtypes ESSENTIAL on 64-bit, else HWND/pointer
    # args are truncated to 32 bits and the messages go nowhere).
    _user32 = _ctypes.WinDLL("user32", use_last_error=True)
    _user32.SendMessageW.restype = _ctypes.c_ssize_t
    _user32.SendMessageW.argtypes = [_wt.HWND, _wt.UINT, _ctypes.c_size_t,
                                     _ctypes.c_size_t]
    _user32.GetForegroundWindow.restype = _wt.HWND
    _user32.GetWindowThreadProcessId.restype = _wt.DWORD
    _user32.GetWindowThreadProcessId.argtypes = [_wt.HWND, _ctypes.c_void_p]
    _user32.GetGUIThreadInfo.restype = _wt.BOOL
    _user32.GetGUIThreadInfo.argtypes = [_wt.DWORD,
                                         _ctypes.POINTER(_GUITHREADINFO)]
else:  # pragma: no cover - non-Windows
    _ctypes = None
    _user32 = None
    _GUITHREADINFO = None


def _focused_hwnd():
    """HWND of the focused control on the foreground GUI thread, or 0."""
    if _user32 is None:
        return 0
    try:
        info = _GUITHREADINFO()
        info.cbSize = _ctypes.sizeof(_GUITHREADINFO)
        fg = _user32.GetForegroundWindow()
        tid = _user32.GetWindowThreadProcessId(fg, None)
        if _user32.GetGUIThreadInfo(tid, _ctypes.byref(info)):
            return int(info.hwndFocus or info.hwndCaret or 0)
    except Exception:
        pass
    return 0


def _win32_caret_pos(hwnd):
    """Caret character offset in ``hwnd`` (a Win32 edit), or ``None``."""
    if _user32 is None or not hwnd:
        return None
    try:
        start = _wt.DWORD()
        end = _wt.DWORD()
        _user32.SendMessageW(hwnd, _EM_GETSEL, _ctypes.addressof(start),
                             _ctypes.addressof(end))
        return int(start.value)
    except Exception:
        return None


def _win32_caret_text(hwnd):
    """``(caret_offset, full_text)`` for a Win32 edit, or ``None``."""
    pos = _win32_caret_pos(hwnd)
    if pos is None:
        return None
    try:
        n = _user32.SendMessageW(hwnd, _WM_GETTEXTLENGTH, 0, 0)
        n = int(n) if n and int(n) > 0 else 0
        buf = _ctypes.create_unicode_buffer(n + 1)
        _user32.SendMessageW(hwnd, _WM_GETTEXT, n + 1, _ctypes.addressof(buf))
        return (pos, buf.value)
    except Exception:
        return None


def _line_at(text, pos):
    """The text of the line containing offset ``pos``.

    Scans for the nearest CR or LF on each side, so it works whether the control
    uses ``\\r\\n`` (Win32 EDIT), bare ``\\r`` (RichEdit) or ``\\n``."""
    n = len(text)
    pos = max(0, min(pos, n))
    start = pos
    while start > 0 and text[start - 1] not in "\r\n":
        start -= 1
    end = pos
    while end < n and text[end] not in "\r\n":
        end += 1
    return text[start:end]


def _word_at(text, pos):
    """The word at or after offset ``pos`` (whitespace-delimited)."""
    for m in _re.finditer(r"\S+", text):
        if m.start() <= pos < m.end() or m.start() >= pos:
            return m.group()
    return ""


class EditableTextHandler:
    """TextPattern-based character / word / line review."""

    def __init__(self, engine):
        self.engine = engine
        self._review = None        # degenerate review-cursor TextRange
        self._review_owner = None  # id() of the native element it belongs to
        self._last_caret = None    # caret range from the last caret-tracking read
        self._last_win32_pos = None  # caret offset (Win32 fallback baseline)
        self._last_spoken = ("", "", 0.0)  # (kind, text, time) for dedup

    # ================================================================== #
    # Focus binding + live-caret reading (caret tracking)
    # ================================================================== #
    def set_element(self, obj):
        """Bind to a newly focused control. Drops the cached review cursor so
        the next review / caret read re-seeds from the live caret. ``obj`` may
        be ``None`` when focus left every editable control."""
        self._review = None
        self._review_owner = None
        # Seed the caret baseline with the position at focus time, so the first
        # arrow read waits for the caret to LEAVE it before reading (no stale
        # first read). Seed whichever backend this control uses.
        self._last_caret = None
        self._last_win32_pos = None
        try:
            text = self._atspi_text()
            if text is not None:
                self._last_caret = text.caret()
                return
            if self._is_win32_edit():
                # Edit-class window: track the caret through Win32 (reliable),
                # not the slow/blocking UIA TextPattern it may also expose.
                self._last_win32_pos = _win32_caret_pos(self._edit_hwnd())
            else:
                tp = self._text_pattern()
                if tp is not None:
                    self._last_caret = self._caret_range(tp)
                else:
                    self._last_win32_pos = _win32_caret_pos(self._edit_hwnd())
        except Exception:
            self._last_caret = None
            self._last_win32_pos = None

    def read_caret_char(self):
        """Read the character at the LIVE caret (not the review cursor).

        Used by caret tracking after an arrow keypress and by the Ctrl+Alt+C
        review command. Port of C# ``EditableTextHandler.GetCharacterAtCaret``.
        """
        return self._read_caret("char")

    def read_caret_word(self):
        return self._read_caret("word")

    def read_caret_line(self):
        return self._read_caret("line")

    # Window classes that are real Win32 edit controls (so EM_GETSEL / WM_GETTEXT
    # work and are reliable). wx.TextCtrl reports class "Edit"; rich editors use
    # the RichEdit family; Scintilla is used by some editors.
    @staticmethod
    def _is_edit_class(cls):
        cls = (cls or "").lower()
        return cls == "edit" or cls.startswith("richedit") or cls.startswith("scintilla")

    def _is_win32_edit(self):
        obj = self.engine.current_object
        if obj is None:
            return False
        return self._is_edit_class(getattr(obj, "class_name", "")) and bool(self._edit_hwnd())

    # ------------------------------------------------------------------ #
    # Linux: the AT-SPI Text interface (caret offset, string at offset)
    # ------------------------------------------------------------------ #
    def _atspi_text(self):
        """``atspi_focus.TextOf`` for the current control, or None (UIA, or
        a control with no Text interface)."""
        obj = self.engine.current_object
        native = getattr(obj, "native", None) if obj is not None else None
        if native is None:
            return None
        try:
            from titan_access import atspi_focus
            if not atspi_focus.is_accessible(native):
                return None
            return atspi_focus.TextOf.of(native)
        except Exception:
            return None

    def _atspi_review_offset(self, text):
        owner = id(getattr(self.engine.current_object, "native", None))
        if self._review is None or self._review_owner != owner or not isinstance(self._review, int):
            self._review = max(0, text.caret())
            self._review_owner = owner
        return self._review

    def _atspi_read_caret(self, text, kind):
        """The unit at the LIVE caret, after the arrow key has moved it: the
        application applies the key after the hook answers, so the read
        waits (up to 0.3 s) for the caret to leave where it was."""
        before = self._last_caret if isinstance(self._last_caret, int) else None
        deadline = time.time() + 0.30
        caret = text.caret()
        while before is not None and caret == before and time.time() < deadline:
            time.sleep(0.01)
            caret = text.caret()
        if caret < 0:
            return False
        self._last_caret = caret
        self._review = caret
        self._review_owner = id(getattr(self.engine.current_object, "native", None))
        content, _s, _e = text.unit(caret, kind)
        if kind == "char" and caret >= text.length():
            content = ""
        self._speak_caret_text(kind, content)
        return True

    def _atspi_read_review(self, text, kind):
        offset = self._atspi_review_offset(text)
        content, _s, _e = text.unit(offset, kind)
        if kind == "char":
            self._speak_char(content)
        else:
            stripped = content.strip()
            empty = L("edit.emptyWord") if kind == "word" else L("edit.emptyLine")
            self.engine.speak(stripped or empty, obj=self.engine.current_object)
        return True

    def _atspi_navigate(self, text, kind, nxt):
        """Move the review cursor one char / word / line and say it. A word
        is the next run of non-blank characters, whatever the toolkit says
        the "word" at a space is."""
        offset = self._atspi_review_offset(text)
        length = text.length()
        target = None
        if kind == "char":
            target = offset + 1 if nxt else offset - 1
            if target < 0 or target >= length:
                target = None
        elif kind == "line":
            _c, start, end = text.unit(offset, "line")
            if nxt:
                target = end if end > offset and end < length else None
            else:
                target = text.unit(start - 1, "line")[1] if start > 0 else None
        else:
            _c, start, end = text.unit(offset, "word")
            if nxt:
                probe = max(end, offset + 1)
                target = self._atspi_skip_blank(text, probe, length, forward=True)
            else:
                probe = (start if start < offset else offset) - 1
                found = self._atspi_skip_blank(text, probe, length, forward=False)
                target = text.unit(found, "word")[1] if found is not None else None
        if target is None:
            self.engine.play("edge.ogg", self.engine.current_object)
            self.engine.speak(L("edit.endOfText") if nxt else L("edit.start"))
            return True
        self._review = target
        content, _s, _e = text.unit(target, kind)
        if kind == "char":
            self._speak_char(content)
        else:
            stripped = content.strip()
            empty = L("edit.emptyWord") if kind == "word" else L("edit.emptyLine")
            self.engine.speak(stripped or empty, obj=self.engine.current_object)
        return True

    @staticmethod
    def _atspi_skip_blank(text, offset, length, forward, limit=400):
        """The nearest non-blank offset from *offset* in the given direction
        (inclusive), or None at the edge of the text."""
        step = 1 if forward else -1
        for _ in range(limit):
            if offset < 0 or offset >= length:
                return None
            ch = text.unit(offset, "char")[0]
            if ch and not ch.isspace():
                return offset
            offset += step
        return None

    def _read_caret(self, kind):
        """Read the char / word / line at the live caret after an arrow move.

        For real Win32 edit windows (classic EDIT, RichEdit -- and wx.TextCtrl,
        which wraps EDIT) we read through Win32 ``EM_GETSEL`` / ``WM_GETTEXT``
        FIRST, even when a UIA TextPattern is also present: those controls' UIA
        TextPattern is slow/unreliable on Windows (its GetSelection lags the real
        caret or blocks), so reading through it announces a STALE line -- the main
        cause of "edit navigation doesn't work". EM_GETSEL is immediate and exact.
        This mirrors NVDA, which uses the legacy edit TextInfo for Edit-class
        windows rather than UIA. Other controls use the UIA TextPattern, with the
        Win32 path as a last-resort fallback when there is no TextPattern at all.
        """
        text = self._atspi_text()
        if text is not None:
            return self._atspi_read_caret(text, kind)
        if self._is_win32_edit():
            if self._read_caret_win32(kind):
                return True
        tp = self._text_pattern()
        if tp is not None:
            return self._read_caret_uia(tp, kind)
        return self._read_caret_win32(kind)

    def _read_caret_uia(self, tp, kind):
        unit = {"char": _UNIT_CHAR, "word": _UNIT_WORD, "line": _UNIT_LINE}[kind]
        # Wait for the caret to actually move before reading: the app applies the
        # arrow keypress only AFTER the keyboard hook returns, so reading on a
        # fixed delay races it and announces the unit being LEFT. The baseline is
        # the caret position from the previous read (or focus), reliably the OLD
        # position, so any real move is detected.
        moved = self._wait_caret_moved(tp)
        caret = self._caret_range(tp)
        if caret is None:
            return False
        # Remember where we ended up so the next arrow waits for a move from here.
        try:
            self._last_caret = caret.Clone()
        except Exception:
            self._last_caret = caret
        text = self._unit_text(caret, unit)
        if _DEBUG_CARET:
            print(f"[TitanAccess][caret] uia kind={kind} moved={moved} "
                  f"read={text!r}")
        if kind == "word" and text.strip() and self._misspelled(caret, unit):
            # **A word the program has underlined in red** (UIA's spelling
            # annotation) says so after the word.
            return self._speak_caret_text(kind, text.strip() + ", "
                                          + L("edit.misspelled"))
        return self._speak_caret_text(kind, text)

    @staticmethod
    def _misspelled(rng, unit):
        """Whether the unit at *rng* carries UIA's spelling-error annotation
        (AnnotationTypes 60001). False where the control answers nothing."""
        if _auto is None:
            return False
        try:
            work = rng.Clone()
            work.ExpandToEnclosingUnit(unit)
            value = work.GetAttributeValue(_auto.TextAttributeId.AnnotationTypesAttribute)
        except Exception:
            return False
        try:
            values = list(value) if not isinstance(value, (int, float)) else [value]
        except Exception:
            return False
        return any(int(one) == 60001 for one in values
                   if isinstance(one, (int, float)))

    # ================================================================== #
    # The selection as it changes, and the formatting at the caret
    # ================================================================== #
    def _selection_text(self):
        """The selected text now, or None where it cannot be asked."""
        text = self._atspi_text()
        if text is not None:
            try:
                return text.selection() or ""
            except Exception:
                return None
        tp = self._text_pattern()
        if tp is not None:
            try:
                sel = tp.GetSelection()
                return (sel[0].GetText(-1) or "") if sel else ""
            except Exception:
                return None
        hwnd = self._edit_hwnd()
        if hwnd and sys.platform.startswith("win"):
            try:
                start = _ctypes.c_int(0)
                end = _ctypes.c_int(0)
                _user32.SendMessageW(hwnd, _EM_GETSEL, _ctypes.addressof(start),
                                     _ctypes.addressof(end))
                info = _win32_caret_text(hwnd)
                if info is None:
                    return None
                _pos, text = info
                lo, hi = sorted((start.value, end.value))
                return text[lo:hi]
            except Exception:
                return None
        return None

    def read_selection_change(self):
        """Shift with an arrow: what was just selected, or unselected.

        The selection before and after are compared as text: what the new
        one has and the old had not was selected, the other way round
        unselected - the words NVDA says, so a user who shift-arrows
        through a line hears each word as it joins the selection.
        """
        time.sleep(0.05)
        now = self._selection_text()
        if now is None:
            return self.read_selection()
        before = getattr(self, "_last_selection", "") or ""
        self._last_selection = now
        if now == before:
            self.engine.speak(L("edit.noSelectionChange"))
            return True
        if len(now) > len(before) and (now.startswith(before) or now.endswith(before)):
            added = now[len(before):] if now.startswith(before) else now[:len(now) - len(before)]
            said = L("edit.selected", self._words(added))
        elif len(before) > len(now) and (before.startswith(now) or before.endswith(now)):
            gone = before[len(now):] if before.startswith(now) else before[:len(before) - len(now)]
            said = L("edit.unselected", self._words(gone))
        elif now:
            said = L("edit.selected", self._words(now))
        else:
            said = L("edit.unselected", self._words(before))
        self.engine.speak(said, obj=self.engine.current_object)
        return True

    def _words(self, text):
        try:
            from titan_access import symbols
            return symbols.text_for_speech(text.strip(), self.engine.settings) \
                or L("edit.emptyWord")
        except Exception:
            return text.strip() or L("edit.emptyWord")

    def read_formatting(self):
        """The font at the caret - name, size, bold, italic, underline -
        out of UIA's text attributes; AT-SPI's text attributes on Linux."""
        parts = []
        text = self._atspi_text()
        if text is not None:
            try:
                native = getattr(self.engine.current_object, "native", None)
                iface = native.get_text_iface() if hasattr(native, "get_text_iface") else native
                attrs = iface.get_attribute_run(max(0, text.caret()), False)[0]
                attrs = dict(attrs or {})
                if attrs.get("family-name"):
                    parts.append(attrs["family-name"])
                if attrs.get("size"):
                    parts.append(L("edit.fontSize", attrs["size"]))
                if str(attrs.get("weight", "")).isdigit() and int(attrs["weight"]) >= 700:
                    parts.append(L("edit.bold"))
                if attrs.get("style") == "italic":
                    parts.append(L("edit.italic"))
                if attrs.get("underline") not in (None, "", "none"):
                    parts.append(L("edit.underline"))
            except Exception:
                pass
        else:
            tp = self._text_pattern()
            rng = self._caret_range(tp) if tp is not None else None
            if rng is not None and _auto is not None:
                try:
                    rng.ExpandToEnclosingUnit(_UNIT_CHAR)
                except Exception:
                    pass
                ids = _auto.TextAttributeId

                def ask(attr):
                    try:
                        value = rng.GetAttributeValue(attr)
                    except Exception:
                        return None
                    if value is None or str(type(value).__name__) in ("POINTER(IUnknown)",):
                        return None
                    return value
                name = ask(ids.FontNameAttribute)
                if isinstance(name, str) and name:
                    parts.append(name)
                size = ask(ids.FontSizeAttribute)
                if isinstance(size, (int, float)) and size:
                    parts.append(L("edit.fontSize", int(round(float(size)))))
                weight = ask(ids.FontWeightAttribute)
                if isinstance(weight, (int, float)) and weight >= 700:
                    parts.append(L("edit.bold"))
                if ask(ids.IsItalicAttribute) is True:
                    parts.append(L("edit.italic"))
                underline = ask(ids.UnderlineStyleAttribute) if hasattr(
                    ids, "UnderlineStyleAttribute") else None
                if isinstance(underline, (int, float)) and underline:
                    parts.append(L("edit.underline"))
        if not parts:
            self.engine.speak(L("edit.noFormatting"))
            return True
        self.engine.speak(", ".join(parts), obj=self.engine.current_object)
        return True

    def _read_caret_win32(self, kind):
        hwnd = self._edit_hwnd()
        if not hwnd:
            return False
        moved = self._wait_caret_moved_win32(hwnd)
        info = _win32_caret_text(hwnd)
        if info is None:
            return False
        pos, text = info
        self._last_win32_pos = pos
        if kind == "char":
            out = text[pos] if 0 <= pos < len(text) else ""
        elif kind == "word":
            out = _word_at(text, pos)
        else:
            out = _line_at(text, pos)
        if _DEBUG_CARET:
            print(f"[TitanAccess][caret] win32 kind={kind} pos={pos} "
                  f"moved={moved} read={out!r}")
        return self._speak_caret_text(kind, out)

    def _speak_caret_text(self, kind, text):
        # Drop an immediate duplicate read of the same unit. A single arrow press
        # can reach the hook twice (e.g. when another screen reader is also
        # running and re-injects the key), which would otherwise read the same
        # line/word/char twice. A true repeat (pressing Down twice on one wrapped
        # line) is >0.25 s apart and still announced.
        now = time.time()
        lk, lt, ltime = self._last_spoken
        if lk == kind and lt == text and (now - ltime) < 0.25:
            return True
        self._last_spoken = (kind, text, now)
        if kind == "char":
            if not text:
                # Caret sits past the last character.
                if self._announce_bounds():
                    self.engine.speak(L("edit.endOfText"))
                return True
            self._speak_char(text)
        else:
            self.engine.speak(self._text_for_speech(kind, text),
                              obj=self.engine.current_object)
        return True

    def _text_for_speech(self, kind, text):
        """A word or a line as the symbol settings want it: punctuation at
        the chosen level said as words, digits grouped, the indent taken
        off - or counted, where the user wants to hear it."""
        settings = self.engine.settings
        try:
            from titan_access import symbols
        except Exception:                            # noqa: BLE001
            stripped = (text or "").strip()
            empty = L("edit.emptyWord") if kind == "word" else L("edit.emptyLine")
            return stripped or empty
        prefix = ""
        body = (text or "").rstrip()
        if kind == "line" and not symbols.trim_wanted(settings):
            body, indent = symbols.trim_leading(body)
            if indent:
                prefix = L("symbols.indent", indent) + ", "
        else:
            body = body.strip()
        said = symbols.text_for_speech(body, settings)
        if not said:
            return L("edit.emptyWord") if kind == "word" else L("edit.emptyLine")
        return prefix + said

    def _wait_caret_moved_win32(self, hwnd, timeout=0.30):
        """Win32 counterpart of :meth:`_wait_caret_moved`: poll ``EM_GETSEL``
        until the caret offset leaves the last-read position, or the timeout."""
        base = self._last_win32_pos
        if base is None:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            pos = _win32_caret_pos(hwnd)
            if pos is None:
                return False
            if pos != base:
                return True
            time.sleep(0.01)
        return False

    def _edit_hwnd(self):
        """The HWND of the focused edit control (for the Win32 fallback)."""
        obj = self.engine.current_object
        h = int(getattr(obj, "hwnd", 0) or 0) if obj is not None else 0
        return h or _focused_hwnd()

    def _wait_caret_moved(self, tp, timeout=0.30):
        """Block until the live caret leaves :attr:`_last_caret`, or the timeout
        elapses.

        This is what makes arrow navigation read the NEW position. The keypress
        is dispatched to the application only after the keyboard hook returns, so
        when this runs the caret may not have moved yet; we poll the live
        selection and return the instant it differs from the last-read position
        (cheap ``CompareEndpoints``). A move that doesn't change the caret (an
        arrow at a document boundary) just falls through on the timeout and reads
        the current position, which is correct there. Returns True if a move was
        detected, False on the timeout (used only for the optional caret trace)."""
        base = self._last_caret
        if base is None:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            cur = self._caret_range(tp)
            if cur is None:
                return False
            try:
                if cur.CompareEndpoints(_EP_START, base, _EP_START) != 0:
                    return True
            except Exception:
                return False
            time.sleep(0.01)
        return False

    def _announce_bounds(self):
        try:
            return bool(self.engine.settings.announce_text_bounds)
        except Exception:
            return False

    # ================================================================== #
    # Reading at the review cursor
    # ================================================================== #
    def read_current_char(self):
        text = self._atspi_text()
        if text is not None:
            return self._atspi_read_review(text, "char")
        tp = self._text_pattern()
        if tp is None:
            return self._cannot()
        rng = self._review_range(tp)
        if rng is None:
            return self._cannot()
        self._speak_char(self._unit_text(rng, _UNIT_CHAR))
        return True

    def read_current_word(self):
        text = self._atspi_text()
        if text is not None:
            return self._atspi_read_review(text, "word")
        tp = self._text_pattern()
        if tp is None:
            return self._cannot()
        rng = self._review_range(tp)
        if rng is None:
            return self._cannot()
        text = self._unit_text(rng, _UNIT_WORD).strip()
        self.engine.speak(text or L("edit.emptyWord"), obj=self.engine.current_object)
        return True

    def read_current_line(self):
        text = self._atspi_text()
        if text is not None:
            return self._atspi_read_review(text, "line")
        tp = self._text_pattern()
        if tp is None:
            return self._cannot()
        rng = self._review_range(tp)
        if rng is None:
            return self._cannot()
        text = self._unit_text(rng, _UNIT_LINE).strip()
        self.engine.speak(text or L("edit.emptyLine"), obj=self.engine.current_object)
        return True

    # ================================================================== #
    # Moving the review cursor
    # ================================================================== #
    def navigate_char(self, next):
        return self._navigate(_UNIT_CHAR, next, read_char=True, kind="char")

    def navigate_word(self, next):
        return self._navigate(_UNIT_WORD, next, read_char=False, kind="word")

    def navigate_line(self, next):
        return self._navigate(_UNIT_LINE, next, read_char=False, kind="line")

    def _navigate(self, unit, next, read_char, kind="char"):
        text = self._atspi_text()
        if text is not None:
            # The kind by NAME: without uiautomation every _UNIT_* is None,
            # and "unit is _UNIT_WORD" would call a line a word.
            return self._atspi_navigate(text, kind, next)
        tp = self._text_pattern()
        if tp is None:
            return self._cannot()
        rng = self._review_range(tp)
        if rng is None:
            return self._cannot()
        count = 1 if next else -1
        try:
            moved = rng.Move(unit, count)
        except Exception as e:
            print(f"[TitanAccess] editable_text: move error: {e}")
            self.engine.speak(L("edit.navError"))
            return True
        if moved == 0:
            # Hit the start/end of the document.
            self.engine.play("edge.ogg", self.engine.current_object)
            self.engine.speak(L("edit.endOfText") if next else L("edit.start"))
            return True
        text = self._unit_text(rng, unit)
        if read_char:
            self._speak_char(text)
        else:
            stripped = text.strip()
            empty = L("edit.emptyWord") if unit is _UNIT_WORD else L("edit.emptyLine")
            self.engine.speak(stripped or empty, obj=self.engine.current_object)
        return True

    # ================================================================== #
    # Position / selection
    # ================================================================== #
    def read_position(self):
        text = self._atspi_text()
        if text is not None:
            caret = text.caret()
            if caret < 0:
                self.engine.speak(L("edit.noPositionInfo"))
                return True
            before = text.all()[:caret]
            line = before.count("\n") + 1
            col = len(before) - (before.rfind("\n") + 1) + 1
            self.engine.speak(L("edit.position", line, col))
            return True
        tp = self._text_pattern()
        if tp is None:
            return self._cannot()
        try:
            caret = self._caret_range(tp)
            if caret is None:
                self.engine.speak(L("edit.noPositionInfo"))
                return True
            doc = tp.DocumentRange.Clone()
            doc.MoveEndpointByRange(_EP_END, caret, _EP_START)
            before = doc.GetText(-1) or ""
            line = before.count("\n") + 1
            col = len(before) - (before.rfind("\n") + 1) + 1
            self.engine.speak(L("edit.position", line, col))
        except Exception as e:
            print(f"[TitanAccess] editable_text: position error: {e}")
            self.engine.speak(L("edit.positionError"))
        return True

    def read_selection(self):
        text = self._atspi_text()
        if text is not None:
            chosen = text.selection()
            if chosen.strip():
                self.engine.speak(chosen, obj=self.engine.current_object)
            else:
                self.engine.speak(L("edit.noSelection"))
            return True
        tp = self._text_pattern()
        if tp is None:
            return self._cannot()
        try:
            sel = tp.GetSelection()
            text = ""
            if sel:
                text = sel[0].GetText(-1) or ""
            if text.strip():
                self.engine.speak(text, obj=self.engine.current_object)
            else:
                self.engine.speak(L("edit.noSelection"))
        except Exception as e:
            print(f"[TitanAccess] editable_text: selection error: {e}")
            self.engine.speak(L("edit.noSelection"))
        return True

    # ================================================================== #
    # Internals
    # ================================================================== #
    def _text_pattern(self):
        """Return the TextPattern of the current object, or None."""
        if _auto is None:
            return None
        obj = self.engine.current_object
        native = getattr(obj, "native", None) if obj is not None else None
        if native is None:
            return None
        try:
            # Prefer the typed getter when the control exposes it.
            if hasattr(native, "GetTextPattern"):
                tp = native.GetTextPattern()
                if tp is not None:
                    return tp
            return native.GetPattern(_TEXT_PATTERN_ID)
        except Exception:
            return None

    def _caret_range(self, tp):
        """A degenerate range at the caret (start of the first selection)."""
        try:
            sel = tp.GetSelection()
            if sel:
                rng = sel[0].Clone()
                rng.MoveEndpointByRange(_EP_END, rng, _EP_START)  # collapse to start
                return rng
        except Exception:
            pass
        try:
            rng = tp.DocumentRange.Clone()
            rng.MoveEndpointByRange(_EP_END, rng, _EP_START)
            return rng
        except Exception:
            return None

    def _review_range(self, tp):
        """Return the review cursor, re-seeding it from the caret when the
        focused element changed (or on first use)."""
        obj = self.engine.current_object
        native = getattr(obj, "native", None) if obj is not None else None
        owner = id(native) if native is not None else None
        if self._review is None or owner != self._review_owner:
            self._review = self._caret_range(tp)
            self._review_owner = owner
        return self._review

    @staticmethod
    def _unit_text(rng, unit):
        """Text of one *unit* starting at the (degenerate) range *rng*."""
        try:
            work = rng.Clone()
            work.ExpandToEnclosingUnit(unit)
            return work.GetText(-1) or ""
        except Exception:
            return ""

    def _speak_char(self, text):
        if not text:
            self.engine.speak(L("edit.emptyChar"))
            return
        ch = text[0]
        try:
            phonetic = bool(self.engine.settings.phonetic_letters)
        except Exception:
            phonetic = False
        # The dial says whether ITS letters are phonetic (`Navigation/
        # PhoneticInDial`); the arrows follow the text-editing setting.
        override = getattr(self, "phonetic_override", None)
        if override is not None:
            phonetic = bool(override)
        # **A capital letter as the user chose** (`Symbols/CapitalLetters`):
        # the word in front, a beep, a higher pitch, or nothing of the
        # kind; a symbol by its name always.
        try:
            from titan_access import symbols
            said, pitch, beep = symbols.describe_char(ch, self.engine.settings,
                                                      phonetic=phonetic)
        except Exception:                            # noqa: BLE001
            said, pitch, beep = character_announcement(
                ch, use_phonetic=phonetic), 0, False
        if beep:
            try:
                self.engine.sound.play_tone(1000, 30, gain=0.4)
            except Exception:                        # noqa: BLE001
                pass
        self.engine.speak(said, obj=self.engine.current_object,
                          pitch_offset=pitch)

    def _cannot(self):
        self.engine.speak(L("edit.cannotNavigate"))
        return True
