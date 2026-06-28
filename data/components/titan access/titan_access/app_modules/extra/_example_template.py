# -*- coding: utf-8 -*-
"""Example Titan Access application module (TEMPLATE — not loaded).

Files whose name starts with ``_`` are skipped by the loader. Copy this file,
rename it to ``<exe>.py`` (e.g. ``notepad++.py``), drop it in this folder or in
``%APPDATA%\\titosoft\\Titan\\screenreader\\app_modules\\`` and restart the reader.

See README.md in this folder for the full API.
"""

from titan_access.app_modules.base import AppModuleBase


class AppModule(AppModuleBase):
    # Inferred from the file name when omitted; set it to be explicit.
    process_name = "example"

    def on_gain_focus(self, obj):
        # One-time welcome the first time the app gains focus this session.
        self._announce_welcome_once("Example application")

    def customize_object(self, obj):
        # Example: append the class name to the description for edit fields.
        if obj is not None and obj.role == "edit" and obj.class_name:
            extra = f"({obj.class_name})"
            obj.description = (obj.description + " " + extra).strip()
        return obj

    def get_gestures(self):
        return {"control+shift+r": self._read_something}

    def _read_something(self, *args):
        self.engine.speak("Example gesture")
