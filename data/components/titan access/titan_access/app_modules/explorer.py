# -*- coding: utf-8 -*-
"""Windows Explorer application module.

Python port of ``ScreenReader/AppModules/ExplorerModule.cs``. Improves file /
folder navigation: appends a friendly file-type description to list items,
announces the current path on the address bar, and adds the nesting level to
folder-tree items.

# LOCALE KEYS TO ADD: explorer.appName = File Explorer
# LOCALE KEYS TO ADD: explorer.folder = folder
# LOCALE KEYS TO ADD: explorer.address = Address: {0}
# LOCALE KEYS TO ADD: file.text = text file
# LOCALE KEYS TO ADD: file.pdf = PDF document
# LOCALE KEYS TO ADD: file.word = Word document
# LOCALE KEYS TO ADD: file.excel = Excel spreadsheet
# LOCALE KEYS TO ADD: file.powerpoint = PowerPoint presentation
# LOCALE KEYS TO ADD: file.image = image
# LOCALE KEYS TO ADD: file.audio = audio file
# LOCALE KEYS TO ADD: file.video = video file
# LOCALE KEYS TO ADD: file.archive = archive
# LOCALE KEYS TO ADD: file.executable = program
# LOCALE KEYS TO ADD: file.library = library
# LOCALE KEYS TO ADD: file.code = C# code
# LOCALE KEYS TO ADD: file.python = Python script
# LOCALE KEYS TO ADD: file.javascript = JavaScript script
# LOCALE KEYS TO ADD: file.web = HTML page
# LOCALE KEYS TO ADD: file.stylesheet = style sheet
# LOCALE KEYS TO ADD: file.json = JSON file
# LOCALE KEYS TO ADD: file.xml = XML file
# LOCALE KEYS TO ADD: file.generic = {0} file
"""

import os

from titan_access.localization import L
from titan_access.app_modules.base import AppModuleBase
from titan_access.contracts import (
    ROLE_LISTITEM, ROLE_GRIDITEM, ROLE_TREEITEM, ROLE_EDIT, ROLE_TREE,
)

# Extension -> locale key for the file-type description.
_FILE_TYPE_KEYS = {
    ".txt": "file.text",
    ".pdf": "file.pdf",
    ".doc": "file.word", ".docx": "file.word",
    ".xls": "file.excel", ".xlsx": "file.excel",
    ".ppt": "file.powerpoint", ".pptx": "file.powerpoint",
    ".jpg": "file.image", ".jpeg": "file.image", ".png": "file.image",
    ".gif": "file.image", ".bmp": "file.image",
    ".mp3": "file.audio", ".wav": "file.audio", ".flac": "file.audio",
    ".ogg": "file.audio",
    ".mp4": "file.video", ".avi": "file.video", ".mkv": "file.video",
    ".mov": "file.video",
    ".zip": "file.archive", ".rar": "file.archive", ".7z": "file.archive",
    ".exe": "file.executable",
    ".dll": "file.library",
    ".cs": "file.code",
    ".py": "file.python",
    ".js": "file.javascript",
    ".html": "file.web", ".htm": "file.web",
    ".css": "file.stylesheet",
    ".json": "file.json",
    ".xml": "file.xml",
}


class ExplorerModule(AppModuleBase):
    process_name = "explorer"

    def __init__(self, engine):
        super().__init__(engine)
        self._last_path = None
        # Cache of the current folder's real directory listing (see
        # _scan_current_folder), keyed by _last_path so it's rebuilt only when
        # the folder actually changes, not on every list-item focus.
        self._dir_cache_path = None
        self._dir_cache = None

    @property
    def app_name(self):
        return L("explorer.appName")

    def on_lose_focus(self, obj):
        self._last_path = None
        self._dir_cache_path = None
        self._dir_cache = None
        super().on_lose_focus(obj)

    def customize_object(self, obj):
        if obj is None:
            return obj
        try:
            # File / folder list items: append a friendly type description.
            if obj.role in (ROLE_LISTITEM, ROLE_GRIDITEM):
                name = obj.name or ""
                if name:
                    if "." in name:
                        # Extension visible in the displayed name -- accurate,
                        # no need to touch the disk.
                        ext = os.path.splitext(name)[1].lower()
                        detail = L(_FILE_TYPE_KEYS.get(ext, "file.generic"), ext)
                    else:
                        # No dot in the displayed name: could be a real folder,
                        # OR a file whose extension Explorer is hiding (the
                        # Windows default "hide extensions for known file
                        # types" setting) -- guessing "folder" from the bare
                        # text alone would misreport a hidden-extension file.
                        # Resolve it against the real folder listing instead.
                        detail = self._real_type_detail(name)
                    obj.description = self._append(obj.description, detail)
                return obj

            # Address bar: announce the current path once.
            if obj.role == ROLE_EDIT and obj.class_name == "Edit" and \
                    "Address" in (obj.name or ""):
                path = obj.value
                if path and path != self._last_path:
                    self._last_path = path
                    obj.description = self._append(obj.description,
                                                   L("explorer.address", path))
                return obj

            # Folder tree items: append the nesting level.
            if obj.role == ROLE_TREEITEM:
                level = obj.level or self._tree_level(obj)
                if level > 0:
                    obj.description = self._append(
                        obj.description, L("engine.hierarchyLevel", level))
        except Exception:
            pass
        return obj

    @staticmethod
    def _append(description, detail):
        if not detail:
            return description
        return f"{description}, {detail}" if description else detail

    def _real_type_detail(self, name):
        """Resolve the real type of an extensionless-looking list item by
        consulting the actual folder contents (real data), instead of assuming
        "folder". Falls back to that same assumption -- today's behavior --
        whenever the real folder can't be listed or the match is ambiguous, so
        this never regresses, it only adds accuracy when the folder is knowable
        (virtual folders like "This PC" or a search-results view have no real
        path and always take the fallback).
        """
        scan = self._scan_current_folder()
        if scan is not None:
            dirs, files_by_stem = scan
            key = name.lower()
            if key in dirs:
                return L("explorer.folder")
            matches = files_by_stem.get(key)
            if matches and len(matches) == 1:
                ext = os.path.splitext(matches[0])[1].lower()
                return L(_FILE_TYPE_KEYS.get(ext, "file.generic"), ext)
        return L("explorer.folder")

    def _scan_current_folder(self):
        """Return ``(dirs, files_by_stem)`` for the current folder (address-bar
        path), cached until the folder changes. ``dirs`` is a set of lower-cased
        subdirectory names; ``files_by_stem`` maps a lower-cased filename stem
        to the list of real filenames sharing it (usually one -- more than one
        means an ambiguous match, e.g. "report.docx" and "report.pdf" both
        present). Returns ``None`` when the folder is unknown or unlistable."""
        path = self._last_path
        if not path:
            return None
        if path == self._dir_cache_path and self._dir_cache is not None:
            return self._dir_cache
        dirs = set()
        files_by_stem = {}
        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.is_dir():
                            dirs.add(entry.name.lower())
                        else:
                            stem = os.path.splitext(entry.name)[0].lower()
                            files_by_stem.setdefault(stem, []).append(entry.name)
                    except OSError:
                        continue
        except OSError:
            return None
        self._dir_cache_path = path
        self._dir_cache = (dirs, files_by_stem)
        return self._dir_cache

    @staticmethod
    def _tree_level(obj):
        """Count tree-item ancestors via the live UIA element (best-effort)."""
        native = getattr(obj, "native", None)
        if native is None:
            return 0
        level = 0
        node = native
        depth = 0
        while node is not None and depth < 40:
            try:
                node = node.GetParentControl()
                if node is None:
                    break
                ctype = node.ControlTypeName
            except Exception:
                break
            if ctype == "TreeItemControl":
                level += 1
            elif ctype == "TreeControl":
                break
            depth += 1
        return level
