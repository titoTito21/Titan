# -*- coding: utf-8 -*-
"""Menu announcement tracker for Titan Access.

Python port of the C# ``ScreenReaderEngine.HandleMenuFocusChange``. Detects when
focus enters a menu bar or an open menu and produces the richer announcement the
C# reader used -- e.g. "Menu bar: File", or "File, menu, 7 items, New" -- plus
the menu open/close sounds. When it handles the announcement it tells the engine
to skip the normal element announcement.

State machine (mirrors the C#): we track whether we are currently in a menu bar
and/or inside an open menu, and the menu container we last announced, so we only
announce transitions (enter menu bar, open menu, open submenu, close menu).
"""

from titan_access.localization import L
from titan_access.contracts import SND_MENU_EXPANDED, SND_MENU_CLOSED


class MenuTracker:
    """Announces menu-bar / menu transitions (port of HandleMenuFocusChange)."""

    def __init__(self, engine):
        self.engine = engine
        self.in_menu = False
        self.in_menu_bar = False
        self._last_menu_id = None

    # ------------------------------------------------------------------ #
    def handle_focus(self, obj) -> bool:
        """Inspect the newly focused element. Returns True if it produced a menu
        announcement (so the engine should NOT also announce the element)."""
        try:
            return self._handle(obj)
        except Exception as e:
            print(f"[TitanAccess] menu_tracker error: {e}")
            return False

    def _handle(self, obj):
        ctrl = getattr(obj, "native", None)
        role = obj.role
        settings = self.engine.settings

        is_menu_item = role in ("menuitem",)
        in_menu_bar_now = is_menu_item and self._in_menu_bar(ctrl)
        menu_parent = self._menu_parent(ctrl)
        in_menu_now = (menu_parent is not None) or role == "menu"

        # --- entered the menu bar ----------------------------------------- #
        if in_menu_bar_now and not self.in_menu_bar:
            self.in_menu_bar = True
            # Port of C# ScreenReaderEngine.HandleMenuFocusChange: announce the
            # "Menu bar" prefix followed by the FULL element description (name +
            # type + state), not just the bare name.
            self.engine.speak(L("menu.menuBar") + ": " + self._describe(obj),
                              obj=obj, interrupt=True)
            return True
        if (not in_menu_bar_now) and self.in_menu_bar and not in_menu_now:
            self.in_menu_bar = False

        # --- opened a menu (or a different submenu) ----------------------- #
        if in_menu_now:
            menu_id = self._menu_id(menu_parent) if menu_parent is not None else None
            if not self.in_menu or menu_id != self._last_menu_id:
                self.in_menu_bar = False
                if settings.get_bool("Verbosity", "MenuSounds", True):
                    self.engine.play(SND_MENU_EXPANDED, obj)
                self._last_menu_id = menu_id
                self.in_menu = True
                # Our own Insert+C reader menu: announce the reader-menu title and
                # the first option as ONE utterance ("Czytnik ekranu. Menu.
                # Ustawienia czytnika ekranu") so nothing cuts the title, instead
                # of the generic "menu, N items, ...".
                if getattr(self.engine, "_menu_host_hwnd", 0):
                    self.engine.speak(
                        L("readerMenu.title") + " " + self._describe(obj),
                        obj=obj, interrupt=True)
                    return True
                self._announce_menu(obj, menu_parent, settings)
                return True
            # Still moving within the same menu -> let the normal announcer run.
            self.in_menu = True
            return False

        # --- left the menu ------------------------------------------------ #
        if (not in_menu_now) and self.in_menu:
            self.in_menu = False
            self._last_menu_id = None
            if in_menu_bar_now:
                # Back to the menu bar: no close sound, announce normally.
                self.in_menu_bar = True
                return False
            if settings.get_bool("Verbosity", "MenuSounds", True):
                self.engine.play(SND_MENU_CLOSED, obj)
            self.engine.speak(L("menu.closed"), interrupt=True)
            self.in_menu_bar = False
            return False

        return False

    # ------------------------------------------------------------------ #
    def _announce_menu(self, obj, menu_parent, settings):
        """Speak "{menu name}, menu, {N} items, {first item}"."""
        parts = []
        if settings.get_bool("Verbosity", "MenuName", True) and menu_parent is not None:
            name = self._name(menu_parent)
            if name:
                parts.append(name)
        parts.append(L("menu.menu"))
        if settings.get_bool("Verbosity", "MenuItemCount", True) and menu_parent is not None:
            count = self._count_items(menu_parent)
            if count > 0:
                parts.append(L("menu.itemCount", count))
        first = self._describe(obj)
        if first:
            parts.append(first)
        self.engine.speak(", ".join(p for p in parts if p), obj=obj, interrupt=True)

    def _describe(self, obj):
        """Full element description (name + type + state), like the C#
        ``UIAutomationHelper.GetElementDescription``. Falls back to the bare
        name if the describer is unavailable."""
        try:
            from titan_access import accessible
            text = accessible.describe_line(obj, self.engine.settings)
            if text:
                return text
        except Exception as e:
            print(f"[TitanAccess] menu_tracker describe error: {e}")
        return obj.name or ""

    # ------------------------------------------------------------------ #
    # UIA tree helpers (operate on a vendored uiautomation.Control)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _in_menu_bar(ctrl):
        node = ctrl
        depth = 0
        while node is not None and depth < 8:
            try:
                if node.ControlTypeName == "MenuBarControl":
                    return True
            except Exception:
                return False
            try:
                node = node.GetParentControl()
            except Exception:
                return False
            depth += 1
        return False

    @staticmethod
    def _menu_parent(ctrl):
        """Nearest ancestor MenuControl (the open menu container), or None."""
        node = ctrl
        depth = 0
        while node is not None and depth < 8:
            try:
                if node.ControlTypeName == "MenuControl":
                    return node
            except Exception:
                return None
            try:
                node = node.GetParentControl()
            except Exception:
                return None
            depth += 1
        return None

    @staticmethod
    def _menu_id(menu):
        try:
            rid = menu.GetRuntimeId()
            if rid:
                return tuple(rid)
        except Exception:
            pass
        try:
            r = menu.BoundingRectangle
            return (r.left, r.top, r.right, r.bottom)
        except Exception:
            return id(menu)

    @staticmethod
    def _name(menu):
        try:
            return (menu.Name or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _count_items(menu):
        try:
            return sum(1 for c in menu.GetChildren()
                       if c.ControlTypeName == "MenuItemControl")
        except Exception:
            return 0
