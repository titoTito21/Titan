# -*- coding: utf-8 -*-
"""Important places navigation.

Python port of ``ScreenReader/Navigation/ImportantPlacesManager.cs``. Provides a
cyclable list of well-known UI locations (desktop, taskbar, Start menu, system
tray, the active app's menu bar, plus app-specific spots for TCE, Explorer and
web browsers). :meth:`navigate` moves to the next/previous place for the
foreground application and focuses the corresponding UI Automation element.

All element lookups go through the vendored ``uiautomation`` package and are
bounded / defensive: if a place cannot be found the manager announces it and
moves on, and the whole module imports cleanly even when UIA is unavailable.

All locale keys used here (``places.*``) already exist in ``locale/*.json``.
"""

import ctypes
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from titan_access.localization import L
from titan_access.contracts import SND_WINDOW, SND_EDGE, SND_ERROR

# --- defensive UIA import --------------------------------------------------- #
try:
    import uiautomation as auto
    _UIA = True
except Exception as _e:  # pragma: no cover
    print(f"[TitanAccess] important_places: uiautomation unavailable: {_e}")
    auto = None
    _UIA = False

# Search bounds so locating a place never stalls the worker thread.
_MAX_DEPTH = 20
_MAX_NODES = 3000


@dataclass
class ImportantPlace:
    """A navigable location: a name plus a finder returning a UIA control."""
    name: str
    description: str = ""
    process: Optional[str] = None        # None => global place
    find: Optional[Callable] = field(default=None, repr=False)


class ImportantPlacesManager:
    """Cyclable list of important places, keyed by the foreground process."""

    def __init__(self, engine):
        self.engine = engine
        self._global: List[ImportantPlace] = []
        self._app: dict = {}
        self._index = -1
        self._build_places()

    # ==================================================================== #
    # Place registry
    # ==================================================================== #
    def _build_places(self):
        self._global = [
            ImportantPlace(L("places.desktop.name"), L("places.desktop.desc"),
                           None, self._find_desktop),
            ImportantPlace(L("places.taskbar.name"), L("places.taskbar.desc"),
                           None, self._find_taskbar),
            ImportantPlace(L("places.startMenu.name"), L("places.startMenu.desc"),
                           None, self._find_start_menu),
            ImportantPlace(L("places.systemTray.name"), L("places.systemTray.desc"),
                           None, self._find_system_tray),
            ImportantPlace(L("places.menuBar.name"), L("places.menuBar.desc"),
                           None, self._find_menu_bar),
        ]

        tce = [
            ImportantPlace(L("places.tce.statusBar.name"), L("places.tce.statusBar.desc"),
                           None, lambda: self._fg_by_type("StatusBarControl")),
            ImportantPlace(L("places.tce.appList.name"), L("places.tce.appList.desc"),
                           None, lambda: self._fg_by_type("ListControl")),
            ImportantPlace(L("places.tce.gameList.name"), L("places.tce.gameList.desc"),
                           None, lambda: self._fg_by_type("ListControl", index=1)),
            ImportantPlace(L("places.tce.menuBar.name"), L("places.tce.menuBar.desc"),
                           None, lambda: self._fg_by_type("MenuBarControl")),
        ]
        for proc in ("tce", "titan", "titancommunicationenvironment"):
            self._app[proc] = tce

        explorer = [
            ImportantPlace(L("places.explorer.addressBar.name"),
                           L("places.explorer.addressBar.desc"), None,
                           self._find_explorer_address),
            ImportantPlace(L("places.explorer.fileList.name"),
                           L("places.explorer.fileList.desc"), None,
                           lambda: self._fg_by_type("DataGridControl")
                           or self._fg_by_type("ListControl")),
            ImportantPlace(L("places.explorer.folderTree.name"),
                           L("places.explorer.folderTree.desc"), None,
                           lambda: self._fg_by_type("TreeControl")),
            ImportantPlace(L("places.explorer.searchBox.name"),
                           L("places.explorer.searchBox.desc"), None,
                           self._find_explorer_search),
            ImportantPlace(L("places.explorer.detailsPane.name"),
                           L("places.explorer.detailsPane.desc"), None,
                           lambda: self._fg_by_name("Details")),
        ]
        self._app["explorer"] = explorer

        browser = [
            ImportantPlace(L("places.browser.addressBar.name"),
                           L("places.browser.addressBar.desc"), None,
                           self._find_browser_address),
            ImportantPlace(L("places.browser.mainContent.name"),
                           L("places.browser.mainContent.desc"), None,
                           lambda: self._fg_by_type("DocumentControl")),
            ImportantPlace(L("places.browser.navigation.name"),
                           L("places.browser.navigation.desc"), None,
                           lambda: self._fg_by_localized("navigation")),
            ImportantPlace(L("places.browser.search.name"),
                           L("places.browser.search.desc"), None,
                           lambda: self._fg_by_localized("search")),
        ]
        for proc in ("chrome", "msedge", "firefox", "brave", "opera",
                     "vivaldi", "chromium"):
            self._app[proc] = browser

    def places_for_current_app(self) -> List[ImportantPlace]:
        places = list(self._global)
        proc = _foreground_process_name()
        if proc and proc in self._app:
            places.extend(self._app[proc])
        return places

    def list_places(self) -> List[str]:
        """Names of the places available for the current foreground app."""
        return [p.name for p in self.places_for_current_app()]

    # ==================================================================== #
    # Navigation
    # ==================================================================== #
    def navigate(self, nxt: bool) -> bool:
        """Cycle to the next (``nxt``) or previous place and activate it."""
        places = self.places_for_current_app()
        if not places:
            self.engine.speak(L("places.none"))
            return False
        if self._index < 0:
            self._index = 0 if nxt else len(places) - 1
        else:
            self._index = (self._index + (1 if nxt else -1)) % len(places)
        place = places[self._index]
        return self._activate(place, self._index, len(places))

    def navigate_to_index(self, index: int) -> bool:
        places = self.places_for_current_app()
        if 0 <= index < len(places):
            self._index = index
            return self._activate(places[index], index, len(places))
        self.engine.speak(L("places.invalidIndex"))
        return False

    def _activate(self, place: ImportantPlace, index: int, total: int) -> bool:
        try:
            element = place.find() if place.find else None
            if element is not None:
                try:
                    element.SetFocus()
                except Exception:
                    pass
                self.engine.play(SND_WINDOW)
                self.engine.speak(L("places.nameWithIndex", place.name,
                                    index + 1, total))
                return True
            self.engine.play(SND_EDGE)
            self.engine.speak(L("places.notFound", place.name))
            return False
        except Exception as e:
            print(f"[TitanAccess] important_places: nav error to {place.name}: {e}")
            self.engine.play(SND_ERROR)
            self.engine.speak(L("places.navError", place.name))
            return False

    # ==================================================================== #
    # Element finders (all return a uiautomation Control or None)
    # ==================================================================== #
    def _find_desktop(self):
        root = _root()
        if root is None:
            return None
        desktop = _child_by_classname(root, "Progman") or \
            _child_by_classname(root, "WorkerW")
        if desktop is None:
            return None
        listview = _find_descendant(desktop, lambda c: _ctype(c) == "ListControl")
        return listview or desktop

    def _find_taskbar(self):
        root = _root()
        return _child_by_classname(root, "Shell_TrayWnd") if root else None

    def _find_start_menu(self):
        root = _root()
        if root is None:
            return None
        start = _child_by_classname(root, "Windows.UI.Core.CoreWindow")
        if start is not None:
            try:
                name = (start.Name or "").lower()
            except Exception:
                name = ""
            if "start" in name or "menu" in name:
                return start
        taskbar = self._find_taskbar()
        if taskbar is not None:
            return _find_descendant(taskbar, lambda c: (_name(c) == "Start"))
        return None

    def _find_system_tray(self):
        taskbar = self._find_taskbar()
        if taskbar is None:
            return None
        tray = _find_descendant(taskbar, lambda c: _classname(c) == "TrayNotifyWnd")
        if tray is not None:
            btn = _find_descendant(tray, lambda c: _ctype(c) == "ButtonControl")
            return btn or tray
        return _find_descendant(taskbar, lambda c: _aid(c) == "SystemTrayIcon")

    def _find_menu_bar(self):
        window = _foreground_window()
        if window is None:
            return None
        return _find_descendant(window, lambda c: _ctype(c) == "MenuBarControl")

    def _find_explorer_address(self):
        window = _foreground_window()
        if window is None:
            return None
        addr = _find_descendant(
            window, lambda c: _ctype(c) in ("EditControl", "ComboBoxControl")
            and "address" in _name(c).lower())
        return addr

    def _find_explorer_search(self):
        window = _foreground_window()
        if window is None:
            return None
        return _find_descendant(
            window, lambda c: _ctype(c) == "EditControl"
            and "search" in _name(c).lower())

    def _find_browser_address(self):
        window = _foreground_window()
        if window is None:
            return None
        return _find_descendant(
            window, lambda c: _ctype(c) in ("EditControl", "ComboBoxControl")
            and ("address" in _name(c).lower() or "search" in _name(c).lower()))

    # -- foreground-window search shortcuts -------------------------------- #
    def _fg_by_type(self, ctype, index=0):
        window = _foreground_window()
        if window is None:
            return None
        if index <= 0:
            return _find_descendant(window, lambda c: _ctype(c) == ctype)
        return _find_descendant_nth(window, lambda c: _ctype(c) == ctype, index)

    def _fg_by_name(self, name):
        window = _foreground_window()
        if window is None:
            return None
        return _find_descendant(window, lambda c: _name(c) == name)

    def _fg_by_localized(self, token):
        window = _foreground_window()
        if window is None:
            return None
        token = token.lower()
        return _find_descendant(
            window, lambda c: token in (_localized(c) or "").lower())


# =========================================================================== #
# UIA / Win32 helpers (defensive)
# =========================================================================== #
def _root():
    if not _UIA:
        return None
    try:
        return auto.GetRootControl()
    except Exception:
        return None


def _foreground_window():
    if not _UIA:
        return None
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            return auto.ControlFromHandle(hwnd)
        return auto.GetForegroundControl()
    except Exception:
        return None


def _child_by_classname(parent, classname):
    if parent is None:
        return None
    try:
        for child in parent.GetChildren():
            if _classname(child) == classname:
                return child
    except Exception:
        pass
    return None


def _find_descendant(root, predicate):
    """First descendant satisfying ``predicate`` (bounded DFS)."""
    if root is None or not _UIA:
        return None
    try:
        count = 0
        for ctrl, _depth in auto.WalkControl(root, includeTop=False,
                                             maxDepth=_MAX_DEPTH):
            count += 1
            if count > _MAX_NODES:
                break
            try:
                if predicate(ctrl):
                    return ctrl
            except Exception:
                continue
    except Exception:
        pass
    return None


def _find_descendant_nth(root, predicate, index):
    """The ``index``-th (0-based) descendant satisfying ``predicate``."""
    if root is None or not _UIA:
        return None
    found = 0
    try:
        count = 0
        for ctrl, _depth in auto.WalkControl(root, includeTop=False,
                                             maxDepth=_MAX_DEPTH):
            count += 1
            if count > _MAX_NODES:
                break
            try:
                if predicate(ctrl):
                    if found == index:
                        return ctrl
                    found += 1
            except Exception:
                continue
    except Exception:
        pass
    return None


def _foreground_process_name() -> str:
    try:
        import ctypes.wintypes as wt
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = wt.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        import os
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        k = ctypes.windll.kernel32
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(512)
            size = wt.DWORD(512)
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.splitext(os.path.basename(buf.value))[0].lower()
        finally:
            k.CloseHandle(h)
    except Exception:
        pass
    return ""


# -- tolerant property accessors -------------------------------------------- #
def _ctype(c):
    try:
        return c.ControlTypeName or ""
    except Exception:
        return ""


def _name(c):
    try:
        return c.Name or ""
    except Exception:
        return ""


def _classname(c):
    try:
        return c.ClassName or ""
    except Exception:
        return ""


def _aid(c):
    try:
        return c.AutomationId or ""
    except Exception:
        return ""


def _localized(c):
    try:
        return c.LocalizedControlType or ""
    except Exception:
        return ""
