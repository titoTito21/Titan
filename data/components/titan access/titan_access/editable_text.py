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
import threading
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
    _user32.SendMessageTimeoutW.restype = _ctypes.c_ssize_t
    _user32.SendMessageTimeoutW.argtypes = [
        _wt.HWND, _wt.UINT, _ctypes.c_size_t, _ctypes.c_size_t, _wt.UINT,
        _wt.UINT, _ctypes.POINTER(_ctypes.c_size_t)]
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


_SMTO_ABORTIFHUNG = 0x0002
#: A field longer than this is not copied on every Backspace.
_SNAPSHOT_LIMIT = 200000


def _send(hwnd, msg, wparam, lparam, timeout_ms):
    """SendMessage, or SendMessageTimeout when *timeout_ms* is given (the
    keyboard hook's thread may not wait on a program that has hung).
    ``None`` when the program did not answer in time."""
    if timeout_ms is None:
        return _user32.SendMessageW(hwnd, msg, wparam, lparam)
    out = _ctypes.c_size_t(0)
    if not _user32.SendMessageTimeoutW(hwnd, msg, wparam, lparam,
                                       _SMTO_ABORTIFHUNG, int(timeout_ms),
                                       _ctypes.byref(out)):
        return None
    return out.value


def _win32_snapshot(hwnd, timeout_ms=None):
    """``{'text', 'caret', 'whole', 't'}`` of a Win32 edit, or None."""
    if _user32 is None or not hwnd:
        return None
    try:
        start = _wt.DWORD()
        end = _wt.DWORD()
        if _send(hwnd, _EM_GETSEL, _ctypes.addressof(start),
                 _ctypes.addressof(end), timeout_ms) is None:
            return None
        n = _send(hwnd, _WM_GETTEXTLENGTH, 0, 0, timeout_ms)
        if n is None:
            return None
        n = int(n) if int(n) > 0 else 0
        if n > _SNAPSHOT_LIMIT:
            return None
        buf = _ctypes.create_unicode_buffer(n + 1)
        if _send(hwnd, _WM_GETTEXT, n + 1, _ctypes.addressof(buf),
                 timeout_ms) is None:
            return None
        return {"text": buf.value, "caret": int(start.value),
                "sel_end": int(end.value), "whole": True, "t": time.time()}
    except Exception:
        return None


def _atspi_snapshot(text):
    """The same of an AT-SPI Text: the whole text when it is short, the
    caret's line otherwise."""
    try:
        caret = text.caret()
        if caret < 0:
            return None
        if text.length() <= 20000:
            return {"text": text.all(), "caret": caret, "whole": True,
                    "t": time.time()}
        content, start, _end = text.unit(caret, "line")
        return {"text": content, "caret": caret - start, "whole": False,
                "t": time.time()}
    except Exception:
        return None


def removed_text(before, after):
    """What a Backspace took away between two snapshots, or None.

    Two whole texts are compared from both ends, which is right whatever
    the key took - a character, a word, a selection, a line break. Two
    LINES (UI Automation gives the caret's line) are compared the same
    way while it is the same line; when the line after ends with the
    whole line before, the line break between them is what went."""
    if not before or not after:
        return None
    b, a = before.get("text") or "", after.get("text") or ""
    if len(a) < len(b):
        p = 0
        top = min(len(a), len(b))
        while p < top and a[p] == b[p]:
            p += 1
        q = 0
        while q < top - p and a[len(a) - 1 - q] == b[len(b) - 1 - q]:
            q += 1
        if p + q == len(a):
            gone = b[p:len(b) - q]
            return gone or None
        return None
    if not before.get("whole") and len(a) > len(b) and b and a.endswith(b):
        return "\n"
    return None


# --------------------------------------------------------------------------- #
# UI Automation text, without the vendored library's sleeps
# --------------------------------------------------------------------------- #
# The vendored ``uiautomation`` wraps every text range in a class whose
# Move / MoveEndpointByUnit / MoveEndpointByRange / ExpandToEnclosingUnit /
# Select end in ``time.sleep(0.5)`` (OPERATION_WAIT_TIME, there for test
# scripts that drive a UI and wait for it) - measured on a WPF TextBox:
# 0.50 s per call, so one caret read cost two seconds and more, and every
# poll of the caret half a second. And its CompareEndpoints hands the COM
# call the WRAPPER, which raises: the wait for the caret to move failed
# silently every time. The edit field speaks to the COM ranges directly.
def _raw_range(rng):
    if isinstance(rng, _FastRange):
        return rng.raw
    return getattr(rng, "textRange", rng)


class _FastRange(object):
    """An IUIAutomationTextRange under the names the wrapper used."""
    __slots__ = ("raw",)

    def __init__(self, raw):
        self.raw = raw

    def Clone(self):
        return _FastRange(self.raw.Clone())

    def CompareEndpoints(self, src, other, target):
        return self.raw.CompareEndpoints(src, _raw_range(other), target)

    def ExpandToEnclosingUnit(self, unit, waitTime=0):
        self.raw.ExpandToEnclosingUnit(unit)
        return True

    def GetText(self, max_length=-1):
        return self.raw.GetText(max_length) or ""

    def Move(self, unit, count, waitTime=0):
        return self.raw.Move(unit, count)

    def MoveEndpointByRange(self, src, other, target, waitTime=0):
        self.raw.MoveEndpointByRange(src, _raw_range(other), target)
        return True

    def MoveEndpointByUnit(self, endpoint, unit, count, waitTime=0):
        return self.raw.MoveEndpointByUnit(endpoint, unit, count)

    def Select(self, waitTime=0):
        self.raw.Select()
        return True

    def GetAttributeValue(self, attribute):
        return self.raw.GetAttributeValue(attribute)

    def __getattr__(self, name):
        return getattr(self.raw, name)


class _FastPattern(object):
    """A TextPattern whose ranges are :class:`_FastRange`."""

    def __init__(self, pattern):
        self._pattern = pattern

    def GetSelection(self):
        return [_FastRange(_raw_range(r)) for r in (self._pattern.GetSelection() or [])]

    @property
    def DocumentRange(self):
        return _FastRange(_raw_range(self._pattern.DocumentRange))

    def __getattr__(self, name):
        return getattr(self._pattern, name)


def _expand(rng, unit):
    """A copy of the UIA range *rng* expanded to *unit*.

    **WPF answers the wrong line at both ends of one** (measured on a
    TextBox): the caret at the very START of a line, expanded to Line,
    answers that line AND the one before; the character at the END of a
    line (its CR LF), expanded, answers that line and the next. So both
    are asked - the caret as it is, and the character at it, NVDA's way
    round the first - and the SHORTEST of them that still holds the caret
    is the line. A control without the fault answers the same twice."""
    work = rng.Clone()
    if _UNIT_CHAR is None or unit == _UNIT_CHAR:
        work.ExpandToEnclosingUnit(unit)
        return work
    try:
        degenerate = work.CompareEndpoints(_EP_START, work, _EP_END) == 0
    except Exception:                                # noqa: BLE001
        degenerate = False
    work.ExpandToEnclosingUnit(unit)
    if not degenerate:
        return work
    candidates = [work]
    # The character at the caret, and the one before it: a caret put at
    # the end of a line by a selection leans FORWARD in WPF, and then the
    # caret and its CR LF both answer two lines - the character before
    # it answers the line it ends.
    for endpoint, step in ((_EP_END, 1), (_EP_START, -1)):
        try:
            probe = rng.Clone()
            if probe.MoveEndpointByUnit(endpoint, _UNIT_CHAR, step) == step:
                probe.ExpandToEnclosingUnit(unit)
                candidates.append(probe)
        except Exception:                            # noqa: BLE001
            pass
    if len(candidates) == 1:
        return work

    def holds(c):
        try:
            return c.CompareEndpoints(_EP_START, rng, _EP_START) <= 0 \
                and c.CompareEndpoints(_EP_END, rng, _EP_START) >= 0
        except Exception:                            # noqa: BLE001
            return True

    def size(c):
        try:
            return len(c.GetText(-1) or "")
        except Exception:                            # noqa: BLE001
            return 1 << 30
    held = [c for c in candidates if holds(c)] or candidates
    return min(held, key=size)


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


# --------------------------------------------------------------------------- #
# Visual lines of a Win32 edit (a field that wraps is read a SCREEN line at a
# time, as NVDA reads it - not a whole paragraph on every Down)
# --------------------------------------------------------------------------- #
_EM_GETLINECOUNT = 0x00BA
_EM_LINEINDEX = 0x00BB
_EM_LINELENGTH = 0x00C1
_EM_LINEFROMCHAR = 0x00C9
#: wParam -1: "the line the caret is on" (or the selection's start).
_WPARAM_MINUS_ONE = (1 << (8 * (_ctypes.sizeof(_ctypes.c_size_t)
                                if _ctypes is not None else 8))) - 1


def _signed(value):
    """An LRESULT read through ``c_size_t`` back as the int it was."""
    if value is None:
        return None
    value = int(value)
    if value >= 1 << 63:
        value -= 1 << 64
    return value


def _win32_lines(hwnd, text_length, wanted=(), timeout_ms=None):
    """``(caret line, line count, {line: (start, length)})`` of a Win32
    edit, the caret's line and the *wanted* offsets from it (-1, +1...)
    and the first and the last line measured; None where the control does
    not answer the EM_ line messages sensibly (a control merely CALLED
    Edit), so nothing is guessed from a wrong answer."""
    if _user32 is None or not hwnd:
        return None
    try:
        count = _signed(_send(hwnd, _EM_GETLINECOUNT, 0, 0, timeout_ms))
        cur = _signed(_send(hwnd, _EM_LINEFROMCHAR, _WPARAM_MINUS_ONE, 0,
                            timeout_ms))
        if count is None or cur is None or count < 1 or not 0 <= cur < count:
            return None
        lines = {}
        for i in {cur, 0, count - 1} | {cur + d for d in wanted}:
            if not 0 <= i < count:
                continue
            start = _signed(_send(hwnd, _EM_LINEINDEX, i, 0, timeout_ms))
            if start is None or not 0 <= start <= text_length:
                return None
            length = _signed(_send(hwnd, _EM_LINELENGTH, start, 0, timeout_ms))
            if length is None or length < 0 or start + length > text_length:
                return None
            lines[i] = (start, length)
        return cur, count, lines
    except Exception:
        return None


def _win32_model(hwnd, timeout_ms=25):
    """The field as the hook's thread may ask it, BEFORE the key reaches
    the program: the whole text, the caret, the selection and the visual
    lines round the caret. None where any answer is missing."""
    snap = _win32_snapshot(hwnd, timeout_ms=timeout_ms)
    if snap is None:
        return None
    got = _win32_lines(hwnd, len(snap["text"]), wanted=(-1, 1),
                       timeout_ms=timeout_ms)
    if got is not None:
        snap["line"], snap["count"], snap["lines"] = got
    return snap


def _line_of(snap, i):
    start, length = snap["lines"][i]
    return snap["text"][start:start + length]


def predict_caret(snap, key, ctrl=False):
    """Where an arrow will put the caret, worked out from the field's own
    text before the program has the key: ``(kind, text, snap after)``, or
    None where it cannot be known for certain.

    This is what makes a field answer like a virtual window - the unit is
    said the moment the key is pressed, out of the model, and the read of
    the real control afterwards only confirms it (or corrects it, where
    the program did something of its own). It never switches modes and
    never plays a sound: it is an ordinary edit field, read faster.

    Only what is certain is predicted: Left/Right (a CR LF is one step,
    as every Windows field takes it), Home/End (the caret's own line),
    Up/Down and Control+Home/End where the visual lines are known. A
    selection collapses rather than moving, Control+arrows stop where
    each program decides, and a model the typing has overtaken is
    behind - none of those is guessed.
    """
    if not snap or snap.get("stale"):
        return None
    text = snap.get("text")
    if text is None:
        return None
    caret = int(snap.get("caret") or 0)
    if snap.get("sel") or int(snap.get("sel_end", caret)) != caret:
        return None
    whole = bool(snap.get("whole"))
    lines = snap.get("lines")
    after = dict(snap)
    if ctrl:
        if not (whole and lines) or key not in ("home", "end"):
            return None
        i = 0 if key == "home" else snap["count"] - 1
        if i not in lines:
            return None
        start, length = lines[i]
        new = start if key == "home" else start + length
        after.update(caret=new, sel_end=new, line=i)
        after.pop("lines", None)
        return "line", _line_of(snap, i), after
    if key in ("left", "right"):
        if not 0 <= caret <= len(text):
            return None
        if key == "left":
            if caret == 0:
                if not whole:
                    return None             # the line before is not known
                new = 0
            else:
                new = caret - 1
                if new > 0 and text[new] == "\n" and text[new - 1] == "\r":
                    new -= 1
        else:
            if caret >= len(text):
                if not whole:
                    return None
                new = caret
            else:
                new = caret + 1
                if text[caret] == "\r" and text[caret + 1:caret + 2] == "\n":
                    new = caret + 2
                if not whole and new >= len(text):
                    return None             # past the line: the next is unknown
        after.update(caret=new, sel_end=new)
        if lines and whole:
            after.pop("lines", None)        # which visual line: asked again
        return "char", (text[new] if new < len(text) else ""), after
    if key in ("home", "end"):
        if whole:
            if not lines or snap.get("line") not in lines:
                return None
            start, length = lines[snap["line"]]
            line = _line_of(snap, snap["line"])
            new = start if key == "home" else start + length
        else:
            line = text
            new = 0 if key == "home" else len(text.rstrip("\r\n"))
        after.update(caret=new, sel_end=new)
        return "line", line, after
    if key in ("up", "down"):
        if not (whole and lines) or int(snap.get("count") or 1) < 2:
            return None                     # one line: each program differs
        cur = snap.get("line")
        if cur not in lines:
            return None
        target = cur + (-1 if key == "up" else 1)
        if not 0 <= target < snap["count"]:
            target = cur                    # the edge: the line stays
        if target not in lines:
            return None
        start, length = lines[target]
        column = caret - lines[cur][0]
        new = start + max(0, min(column, length))
        after.update(caret=new, sel_end=new, line=target)
        after.pop("lines", None)
        return "line", _line_of(snap, target), after
    return None


def _same_unit(kind, a, b):
    """Whether two reads of one unit say the same thing."""
    if kind == "char":
        norm = lambda t: "\n" if t in ("\r", "\n", "\r\n") else (t or "")
        return norm(a) == norm(b)
    return (a or "").strip() == (b or "").strip()


class EditableTextHandler:
    """TextPattern-based character / word / line review."""

    def __init__(self, engine):
        self.engine = engine
        self._review = None        # degenerate review-cursor TextRange
        self._review_owner = None  # id() of the native element it belongs to
        self._last_caret = None    # caret range from the last caret-tracking read
        self._last_win32_pos = None  # caret offset (Win32 fallback baseline)
        self._last_spoken = ("", "", 0.0)  # (kind, text, time) for dedup
        # The field's text as last read, for Backspace to compare against
        # where it cannot be read on the hook's thread (UI Automation).
        self._snap = None
        self._typed_at = 0.0
        # What the model said for the last arrow before the program had it
        # (``(kind, text, time)``); the read of the real control that
        # follows is silent when it says the same (`predict_caret_move`).
        self._predicted = None

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
        self._snap = None
        self._predicted = None
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
                    self._snap = self._uia_snapshot(tp)
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
        deadline = time.time() + 0.15
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
            said = self._speak_caret_text(kind, text.strip() + ", "
                                          + L("edit.misspelled"))
        else:
            said = self._speak_caret_text(kind, text)
        # Said first, then the line is kept for the next Backspace: the
        # caret has moved, and what was typed before it no longer counts.
        self._snap = self._uia_snapshot(tp)
        return said

    @staticmethod
    def _misspelled(rng, unit):
        """Whether the unit at *rng* carries UIA's spelling-error annotation
        (AnnotationTypes 60001). False where the control answers nothing."""
        if _auto is None:
            return False
        try:
            work = _expand(rng, unit)
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
    # Deleting: Backspace says what went, Delete what is there now
    # ================================================================== #
    def note_typed(self):
        """A character was typed (the hook's thread). The snapshot is now
        behind the text; for UI Automation a fresh one is taken once the
        typing pauses, on the reader's own thread."""
        self._typed_at = time.time()
        if self._snap is None or self._snap.get("whole"):
            return
        stamp = self._typed_at

        def _refresh():
            if self._typed_at != stamp:
                return                    # typed again since; a later one runs
            tp = self._text_pattern()
            if tp is not None:
                self._snap = self._uia_snapshot(tp)
                # The caret moved with the typing: the next arrow waits for
                # it to leave where it is NOW.
                self._last_caret = self._caret_range(tp)

        def _post():
            try:
                self.engine.submit_action(_refresh)
            except Exception:                        # noqa: BLE001
                pass

        # One scheduler thread, not a thread per key typed.
        from titan_access import later
        later.call_later(0.12, _post)

    def note_caret_key(self):
        """An arrow is about to reach the application (the hook's thread):
        where the caret is now is the position the read waits for it to
        leave. Asked of a Win32 edit with a 20 ms timeout and of AT-SPI on
        the main thread; UI Automation keeps the baseline of its last read.
        Without this, a caret moved by typing left the baseline behind,
        and an arrow that landed back on it waited out the whole timeout."""
        try:
            if self._is_win32_edit():
                hwnd = self._edit_hwnd()
                start = _wt.DWORD()
                end = _wt.DWORD()
                if _send(hwnd, _EM_GETSEL, _ctypes.addressof(start),
                         _ctypes.addressof(end), 20) is not None:
                    self._last_win32_pos = int(start.value)
                return
            if not sys.platform.startswith("win") \
                    and threading.current_thread() is threading.main_thread():
                text = self._atspi_text()
                if text is not None:
                    caret = text.caret()
                    if caret >= 0:
                        self._last_caret = caret
        except Exception:                            # noqa: BLE001
            pass

    def _model_before_key(self):
        """The field as it stands before the program has the key, from
        wherever it may be asked on the hook's thread (`snapshot_before_key`
        for the rules): a Win32 edit with its visual lines, AT-SPI on the
        main thread, otherwise the line the last read kept."""
        if self._is_win32_edit():
            return _win32_model(self._edit_hwnd())
        if not sys.platform.startswith("win") \
                and threading.current_thread() is threading.main_thread():
            text = self._atspi_text()
            if text is not None:
                snap = _atspi_snapshot(text)
                if snap is not None:
                    try:
                        chosen = text.selection()
                        snap["sel"] = bool(chosen)
                    except Exception:            # noqa: BLE001
                        pass
                return snap
        snap = self._snap
        if snap is None:
            return None
        snap = dict(snap)
        snap["stale"] = snap.get("t", 0.0) < self._typed_at + 0.05
        return snap

    def predict_caret_move(self, key, ctrl=False):
        """An arrow is about to reach the program (the hook's thread): say
        at once what it will land on, out of the field's own text
        (`predict_caret`), and leave the read of the real control to
        confirm it. Returns ``(kind, text)`` when something was said, None
        when the read decides alone - as before."""
        self._predicted = None
        # Which key this read answers: the repeat filter below is for one
        # key delivered twice, never for Home pressed right after Down.
        self._key_now = (key, bool(ctrl))
        try:
            snap = self._model_before_key()
        except Exception:                            # noqa: BLE001
            snap = None
        if snap is None:
            return None
        if snap.get("whole"):
            # Where the caret is NOW is what the confirming read waits for
            # it to leave.
            if self._is_win32_edit():
                self._last_win32_pos = int(snap.get("caret") or 0)
            elif isinstance(self._last_caret, int) or self._last_caret is None:
                self._last_caret = int(snap.get("caret") or 0)
        got = predict_caret(snap, key, ctrl)
        if got is None:
            return None
        kind, text, after = got
        after["t"] = time.time()
        if not after.get("whole"):
            # The line the last read kept, moved with the caret, so the
            # next arrow is answered at once as well.
            self._snap = after
        self._predicted = (kind, text, time.time())
        self._speak_caret_text(kind, text, predicted=True)
        return kind, text

    def _rebase_caret(self, snap):
        """After a deletion the caret is somewhere new; the next arrow
        waits for it to leave THERE."""
        if snap is None:
            return
        try:
            if snap.get("whole") and self._is_win32_edit():
                self._last_win32_pos = int(snap.get("caret") or 0)
            elif self._atspi_text() is not None:
                self._last_caret = self._atspi_text().caret()
            else:
                tp = self._text_pattern()
                if tp is not None:
                    self._last_caret = self._caret_range(tp)
        except Exception:                            # noqa: BLE001
            pass

    def _uia_snapshot(self, tp):
        """The caret's line and where in it the caret is (UI Automation)."""
        caret = self._caret_range(tp)
        if caret is None or _UNIT_LINE is None:
            return None
        try:
            line = _expand(caret, _UNIT_LINE)
            text = line.GetText(-1) or ""
            before = line.Clone()
            before.MoveEndpointByRange(_EP_END, caret, _EP_START)
            at = len(before.GetText(-1) or "")
        except Exception:
            return None
        selected = False
        try:
            sel = tp.GetSelection()
            selected = bool(sel) and bool(sel[0].GetText(1))
        except Exception:                            # noqa: BLE001
            pass
        return {"text": text, "caret": at, "whole": False, "sel": selected,
                "t": time.time()}

    def _snapshot_now(self):
        """The field as it is now, through whatever it answers."""
        text = self._atspi_text()
        if text is not None:
            return _atspi_snapshot(text)
        if self._is_win32_edit():
            snap = _win32_snapshot(self._edit_hwnd())
            if snap is not None:
                return snap
        tp = self._text_pattern()
        if tp is not None:
            return self._uia_snapshot(tp)
        return _win32_snapshot(self._edit_hwnd())

    def snapshot_before_key(self):
        """The field before the application has the key - on the HOOK's
        thread, so nothing here may wait: a Win32 edit is asked with a
        40 ms timeout, AT-SPI only on the main thread (where libatspi
        lives), and UI Automation, which cannot be asked from here, answers
        with the line kept by the last read, marked stale when something
        was typed after it."""
        if self._is_win32_edit():
            snap = _win32_snapshot(self._edit_hwnd(), timeout_ms=40)
            if snap is not None:
                return snap
        if not sys.platform.startswith("win") \
                and threading.current_thread() is threading.main_thread():
            text = self._atspi_text()
            if text is not None:
                return _atspi_snapshot(text)
        snap = self._snap
        if snap is None:
            return None
        snap = dict(snap)
        snap["stale"] = snap.get("t", 0.0) < self._typed_at + 0.05
        return snap

    def _wait_text_changed(self, before, timeout=0.30):
        """The field once the key has changed it, or as it is at the
        timeout (a Backspace at the start changes nothing)."""
        if before is None:
            time.sleep(0.05)
            return self._snapshot_now()
        deadline = time.time() + timeout
        after = self._snapshot_now()
        while after is not None and time.time() < deadline \
                and after.get("text") == before.get("text") \
                and after.get("caret") == before.get("caret"):
            time.sleep(0.01)
            after = self._snapshot_now()
        return after

    def read_deletion(self, key, ctrl, before, typed=""):
        """Backspace: the character it took (Control: the word); Delete:
        the character the caret is on now (Control: the word) - NVDA's
        answers to both keys."""
        typed = typed or ""
        stale = bool(before and before.get("stale"))
        after = self._wait_text_changed(None if stale else before)
        if after is not None and not after.get("whole"):
            self._snap = after
        self._rebase_caret(after)
        if key == "delete":
            return self._say_at_caret(after, "word" if ctrl else "char")
        gone = None
        if not stale:
            gone = removed_text(before, after)
        if gone is None and typed and (time.time() - self._typed_at) < 2.0:
            # What was just typed is what Backspace takes back, even where
            # the field could not be read in time.
            gone = typed if ctrl else typed[-1]
        if gone is None:
            if before is not None and after is not None \
                    and before.get("text") == after.get("text") \
                    and self._announce_bounds():
                self.engine.speak(L("edit.start"))
            return False
        self._say_removed(gone)
        return True

    def _say_removed(self, gone):
        if gone.replace("\r", "").replace("\n", "") == "":
            self.engine.speak(L("edit.lineBreak"), obj=self.engine.current_object)
            return
        gone = gone.replace("\r\n", "\n")
        if len(gone) == 1:
            self._speak_char(gone)
            return
        if not gone.strip():
            self._speak_char(gone[0])
            return
        self.engine.speak(self._text_for_speech("word", gone),
                          obj=self.engine.current_object)

    def _say_at_caret(self, snap, kind):
        if snap is None:
            return self._read_caret(kind)
        text, at = snap.get("text") or "", int(snap.get("caret") or 0)
        if kind == "word":
            return self._speak_caret_text("word", _word_at(text, at))
        ch = text[at] if 0 <= at < len(text) else ""
        if ch in ("\r", "\n"):
            self.engine.speak(L("edit.lineBreak"), obj=self.engine.current_object)
            return True
        self._last_spoken = ("", "", 0.0)
        return self._speak_caret_text("char", ch)

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
            out = self._win32_visual_line(hwnd, text, pos)
        if _DEBUG_CARET:
            print(f"[TitanAccess][caret] win32 kind={kind} pos={pos} "
                  f"moved={moved} read={out!r}")
        return self._speak_caret_text(kind, out)

    @staticmethod
    def _win32_visual_line(hwnd, text, pos):
        """The SCREEN line the caret is on: a field that wraps holds a
        paragraph on several lines, and Up/Down move by those. The
        control is asked (EM_LINEFROMCHAR knows which side of a wrap the
        caret is on); a control that does not answer is read by its line
        breaks, as before."""
        got = _win32_lines(hwnd, len(text), timeout_ms=200)
        if got is not None:
            cur, _count, lines = got
            start, length = lines[cur]
            if start <= pos <= start + length + 2:
                return text[start:start + length]
        return _line_at(text, pos)

    def _speak_caret_text(self, kind, text, predicted=False):
        now = time.time()
        if predicted:
            # Said the moment the key was pressed; a key pressed twice on
            # "aa" is two answers, so the repeat filter is not asked.
            self._last_spoken = (kind, text, now)
            self._spoken_for = getattr(self, "_key_now", None)
        else:
            # **The read that confirms a prediction says nothing** when the
            # program did what the model said; where it did something of
            # its own, what it really did is said over the prediction.
            p, self._predicted = self._predicted, None
            # Bound to the KEY, not to a clock: the next key clears it, so
            # a slow program confirming late is still the same answer.
            if p is not None and p[0] == kind and (now - p[2]) < 10.0 \
                    and _same_unit(kind, p[1], text):
                self._last_spoken = (kind, text, now)
                return True
            # Drop an immediate duplicate read of the same unit. A single
            # arrow press can reach the hook twice (e.g. when another screen
            # reader is also running and re-injects the key), which would
            # otherwise read the same line/word/char twice. A true repeat
            # (pressing Down twice on one wrapped line) is >0.25 s apart and
            # still announced.
            lk, lt, ltime = self._last_spoken
            key = getattr(self, "_key_now", None)
            if lk == kind and lt == text and (now - ltime) < 0.25 \
                    and getattr(self, "_spoken_for", None) == key:
                return True
            self._last_spoken = (kind, text, now)
            self._spoken_for = key
        if kind == "char":
            if not text:
                # Caret sits past the last character.
                if self._announce_bounds():
                    self.engine.speak(L("edit.endOfText"))
                return True
            if text[0] in "\r\n":
                # The end of a line: a CR has no name of its own, and
                # saying nothing there sounds like a dead key.
                self.engine.speak(L("edit.lineBreak"),
                                  obj=self.engine.current_object)
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

    def _wait_caret_moved_win32(self, hwnd, timeout=0.15):
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

    def _wait_caret_moved(self, tp, timeout=0.25):
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
            tp = None
            if hasattr(native, "GetTextPattern"):
                tp = native.GetTextPattern()
            if tp is None:
                tp = native.GetPattern(_TEXT_PATTERN_ID)
            return _FastPattern(tp) if tp is not None else None
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
            return _expand(rng, unit).GetText(-1) or ""
        except Exception:
            return ""

    def _speak_char(self, text):
        if not text:
            self.engine.speak(L("edit.emptyChar"))
            return
        ch = text[0]
        if ch in "\r\n":
            self.engine.speak(L("edit.lineBreak"), obj=self.engine.current_object)
            return
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
