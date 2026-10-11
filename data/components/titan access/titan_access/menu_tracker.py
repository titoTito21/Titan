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
        # (menu id, container, container's menu) of a menu whose first item
        # was selected for the user and has not been focused yet.
        self._pending = None

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

        # On Linux a menu bar's own entries are MENUs (GTK): a top-level
        # menu is an item OF THE BAR, and its dropdown is the menu that
        # opens under it - the shape UIA gives on Windows, where the bar's
        # entries are MenuItems and the dropdown a MenuControl of its own.
        top_level_menu = role == "menu" and self._is_top_level_menu(ctrl)
        is_menu_item = role in ("menuitem",) or top_level_menu
        in_menu_bar_now = is_menu_item and self._in_menu_bar(ctrl)
        menu_parent = self._menu_parent(ctrl)
        in_menu_now = (menu_parent is not None) or (role == "menu" and not top_level_menu)

        # --- entered the menu bar ----------------------------------------- #
        if in_menu_bar_now and not self.in_menu_bar:
            self.in_menu_bar = True
            # Port of C# ScreenReaderEngine.HandleMenuFocusChange: announce the
            # "Menu bar" prefix followed by the FULL element description (name +
            # type + state), not just the bare name.
            self._speak_parts([(L("menu.menuBar"), -4)] + self._segments(obj),
                              obj)
            return True
        if (not in_menu_bar_now) and self.in_menu_bar and not in_menu_now:
            self.in_menu_bar = False

        # --- opened a menu (or a different submenu) ----------------------- #
        if in_menu_now:
            menu_id = self._menu_id(menu_parent) if menu_parent is not None else None
            on_container = role == "menu" and not top_level_menu
            pending = self._pending
            if pending is not None and menu_id == pending[0] and not on_container:
                # The first item, selected for the user: the opening is
                # announced now, title and item as ONE utterance.
                self._pending = None
                self._announce_opening(obj, menu_parent, settings)
                return True
            if not self.in_menu or menu_id != self._last_menu_id:
                self.in_menu_bar = False
                if settings.get_bool("Verbosity", "MenuSounds", True):
                    self.engine.play(SND_MENU_EXPANDED, obj)
                self._last_menu_id = menu_id
                self.in_menu = True
                if on_container and self._can_select_first():
                    # **The keyboard is put ON the menu.** A popup opened
                    # with nothing selected (Insert+C, a context menu
                    # opened from code) took the arrows only after one
                    # Down; the first item is selected here and the
                    # opening is said when it is focused.
                    self._pending = (menu_id, obj, menu_parent)
                    self._fallback(menu_id)
                    return True
                self._announce_opening(obj, menu_parent, settings)
                return True
            # Still moving within the same menu -> let the normal announcer run.
            self.in_menu = True
            return False

        # --- left the menu ------------------------------------------------ #
        if (not in_menu_now) and self.in_menu:
            self._pending = None
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
    def _announce_opening(self, obj, menu_parent, settings):
        """A menu has just opened and ``obj`` is where the keyboard is."""
        # Our own Insert+C reader menu: "Titan Access" (pause) "menu" and
        # then the first option, as ONE announcement - the reader's own
        # parts, at their own tones with the reader's pause between them,
        # so nothing cuts the title off.
        if getattr(self.engine, "_menu_host_hwnd", 0):
            parts = [(L("readerMenu.titleName"), 0),
                     (L("readerMenu.titleKind"), -4)]
            if not (getattr(obj, "role", "") == "menu"):
                parts.extend(self._segments(obj))
            self._speak_parts(parts, obj)
            return
        self._announce_menu(obj, menu_parent, settings)

    def _speak_parts(self, parts, obj):
        speak = getattr(self.engine, "speak_segments", None)
        if callable(speak):
            try:
                speak(parts)
                return
            except Exception as e:
                print(f"[TitanAccess] menu_tracker speak error: {e}")
        self.engine.speak(" ".join(p[0] for p in parts if p and p[0]),
                          obj=obj, interrupt=True)

    def _segments(self, obj):
        """The item as the reader reads a control - its own parts."""
        try:
            from titan_access import accessible
            made = accessible.describe(obj, self.engine.settings)
            if made:
                return [tuple(seg) for seg in made if seg and seg[0]]
        except Exception as e:
            print(f"[TitanAccess] menu_tracker segments error: {e}")
        name = getattr(obj, "name", "") or ""
        return [(name, 0)] if name else []

    @staticmethod
    def _can_select_first():
        """Windows only - a GTK menu selects its first item itself."""
        import sys
        return sys.platform == "win32"

    #: How long a menu that opened on its container is given to select an
    #: item by itself (Explorer's context menu does) before Down is pressed
    #: for the user - pressing it then would skip the first item.
    SELECT_AFTER_S = 0.15
    #: When the opening is said on the container after all.
    FALLBACK_AFTER_S = 0.9

    def _press_down(self, menu_id):
        """Press Down for the user, marked so the reader does not hear it
        as theirs - only while the menu is still open on its container."""
        pending = self._pending
        if pending is None or pending[0] != menu_id or not self.in_menu:
            return
        try:
            from titan_access import keyboard_hook
            keyboard_hook.pass_key(0x28)
        except Exception as e:
            print(f"[TitanAccess] menu_tracker select first: {e}")

    def _fallback(self, menu_id):
        """Select the first item a moment after the menu opened; where that
        reached no item (an empty menu, a program that ignores it), the
        opening is still said - on the container."""
        import threading

        down = threading.Timer(self.SELECT_AFTER_S, self._press_down,
                               args=(menu_id,))
        down.daemon = True
        down.start()

        def check():
            pending = self._pending
            if pending is None or pending[0] != menu_id:
                return
            self._pending = None
            _id, container, parent = pending
            try:
                self._announce_opening(container, parent, self.engine.settings)
            except Exception as e:
                print(f"[TitanAccess] menu_tracker fallback: {e}")

        def later():
            post = getattr(self.engine, "post_to_worker", None)
            if callable(post):
                try:
                    post(check)
                    return
                except Exception:
                    pass
            check()

        timer = threading.Timer(self.FALLBACK_AFTER_S, later)
        timer.daemon = True
        timer.start()

    def _announce_menu(self, obj, menu_parent, settings):
        """Speak "{menu name}, menu, {N} items, {first item}"."""
        # The reader's own parts with its pause between them - "Plik"
        # (pause) "menu" (pause) "7 elementów" - never one comma-joined line.
        parts = []
        if settings.get_bool("Verbosity", "MenuName", True) and menu_parent is not None:
            name = self._name(menu_parent)
            if name:
                parts.append((name, 0))
        parts.append((L("menu.menu"), -4))
        if settings.get_bool("Verbosity", "MenuItemCount", True) and menu_parent is not None:
            count = self._count_items(menu_parent)
            if count > 0:
                parts.append((L("menu.itemCount", count), 4))
        if not (getattr(obj, "role", "") == "menu"):
            parts.extend(self._segments(obj))
        self._speak_parts(parts, obj)

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
    def _is_atspi(node):
        """An Atspi.Accessible (Linux) rather than a uiautomation Control."""
        return node is not None and not hasattr(node, "ControlTypeName") and hasattr(node, "get_role")

    @staticmethod
    def _atspi_role_name(node):
        try:
            return node.get_role_name() or ""
        except Exception:
            return ""

    @staticmethod
    def _is_top_level_menu(ctrl):
        """An AT-SPI MENU whose parent is the MENU_BAR - an entry of the bar."""
        if not MenuTracker._is_atspi(ctrl):
            return False
        try:
            parent = ctrl.get_parent()
            return parent is not None and MenuTracker._atspi_role_name(parent) == "menu bar"
        except Exception:
            return False

    @staticmethod
    def _in_menu_bar(ctrl):
        node = ctrl
        depth = 0
        atspi = MenuTracker._is_atspi(ctrl)
        while node is not None and depth < 8:
            try:
                if atspi:
                    name = MenuTracker._atspi_role_name(node)
                    if name == "menu bar":
                        return True
                    # Everything under a GTK menu bar has the bar as an
                    # ancestor; an item inside a dropdown is in THAT menu.
                    if name == "menu" and node is not ctrl:
                        return False
                elif node.ControlTypeName == "MenuBarControl":
                    return True
            except Exception:
                return False
            try:
                node = node.get_parent() if atspi else node.GetParentControl()
            except Exception:
                return False
            depth += 1
        return False

    @staticmethod
    def _menu_parent(ctrl):
        """Nearest ancestor MenuControl (the open menu container), or None.

        On Linux a GTK menu is a MENU whose items are MENU_ITEMs, and the
        menu bar's own entries are MENUs too: the menu a focused item is
        in is the nearest MENU above it, and a focused top-level MENU with
        no MENU above it is on the bar, not in a menu."""
        node = ctrl
        depth = 0
        atspi = MenuTracker._is_atspi(ctrl)
        if atspi:
            try:
                node = ctrl.get_parent()
            except Exception:
                return None
        while node is not None and depth < 8:
            try:
                if atspi:
                    if MenuTracker._atspi_role_name(node) == "menu":
                        return node
                elif node.ControlTypeName == "MenuControl":
                    return node
            except Exception:
                return None
            try:
                node = node.get_parent() if atspi else node.GetParentControl()
            except Exception:
                return None
            depth += 1
        return None

    @staticmethod
    def _menu_id(menu):
        if MenuTracker._is_atspi(menu):
            try:
                from titan_access import atspi_focus
                return ("atspi",) + atspi_focus.path_key(menu)
            except Exception:
                return id(menu)
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
            if MenuTracker._is_atspi(menu):
                return (menu.get_name() or "").strip()
            return (menu.Name or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _count_items(menu):
        try:
            if MenuTracker._is_atspi(menu):
                count = 0
                for i in range(min(int(menu.get_child_count()), 200)):
                    child = menu.get_child_at_index(i)
                    if child is not None and MenuTracker._atspi_role_name(child) in (
                            "menu item", "check menu item", "radio menu item", "menu"):
                        count += 1
                return count
            return sum(1 for c in menu.GetChildren()
                       if c.ControlTypeName == "MenuItemControl")
        except Exception:
            return 0
