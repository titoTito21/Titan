# -*- coding: utf-8 -*-
"""Notepad application module.

Python port of ``ScreenReader/AppModules/NotepadModule.cs``. Announces a short
welcome when Notepad becomes active and appends document statistics (line /
character counts) when the main edit field gains focus.

# LOCALE KEYS TO ADD: notepad.stats = {0} lines, {1} characters
"""

from titan_access.localization import L
from titan_access.app_modules.base import AppModuleBase
from titan_access.contracts import ROLE_EDIT, ROLE_DOCUMENT


class NotepadModule(AppModuleBase):
    process_name = "notepad"

    @property
    def app_name(self):
        return L("notepad.appName")

    def on_gain_focus(self, obj):
        self._announce_welcome_once(L("notepad.welcome"))

    def customize_object(self, obj):
        if obj is None or obj.role not in (ROLE_EDIT, ROLE_DOCUMENT):
            return obj
        # Only the main editing surface (class "Edit" in classic Notepad, or the
        # document control in the modern app).
        if obj.class_name and obj.class_name != "Edit" and obj.role != ROLE_DOCUMENT:
            return obj
        text = self._document_text(obj)
        if text is None:
            return obj
        char_count = len(text)
        if char_count > 0:
            line_count = text.count("\n") + 1
            stats = L("notepad.stats", line_count, char_count)
            obj.description = f"{obj.description}, {stats}".strip(", ") if obj.description else stats
        else:
            obj.description = L("notepad.emptyDoc", obj.description or "").strip(", ")
        return obj

    @staticmethod
    def _document_text(obj):
        """Read the editor's full text via TextPattern, falling back to value."""
        native = getattr(obj, "native", None)
        if native is not None:
            try:
                tp = native.GetTextPattern()
                if tp is not None:
                    return tp.DocumentRange.GetText(-1)
            except Exception:
                pass
        if obj.value:
            return obj.value
        return None
