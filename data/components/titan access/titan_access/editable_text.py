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

from titan_access.localization import L, character_announcement

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


class EditableTextHandler:
    """TextPattern-based character / word / line review."""

    def __init__(self, engine):
        self.engine = engine
        self._review = None        # degenerate review-cursor TextRange
        self._review_owner = None  # id() of the native element it belongs to

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
