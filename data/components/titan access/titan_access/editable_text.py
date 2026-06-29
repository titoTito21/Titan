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
        return self._speak_caret_text(kind, text)

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
            stripped = text.strip()
            empty = L("edit.emptyWord") if kind == "word" else L("edit.emptyLine")
            self.engine.speak(stripped or empty, obj=self.engine.current_object)
        return True

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
        tp = self._text_pattern()
        if tp is None:
            return self._cannot()
        rng = self._review_range(tp)
        if rng is None:
            return self._cannot()
        self._speak_char(self._unit_text(rng, _UNIT_CHAR))
        return True

    def read_current_word(self):
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
        return self._navigate(_UNIT_CHAR, next, read_char=True)

    def navigate_word(self, next):
        return self._navigate(_UNIT_WORD, next, read_char=False)

    def navigate_line(self, next):
        return self._navigate(_UNIT_LINE, next, read_char=False)

    def _navigate(self, unit, next, read_char):
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
        self.engine.speak(character_announcement(ch, use_phonetic=phonetic),
                          obj=self.engine.current_object)

    def _cannot(self):
        self.engine.speak(L("edit.cannotNavigate"))
        return True
