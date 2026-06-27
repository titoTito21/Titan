# -*- coding: utf-8 -*-
"""NumPad object navigation for Titan Access.

Python port of the NumPad object-navigation walk in the C# ``ScreenReaderEngine``
(``OnMoveToNextElement`` / ``OnMoveToPreviousElement`` / ``OnMoveToParent`` /
``OnMoveToFirstChild`` and the ``AnnounceElement`` driven sibling/parent/child
traversal of the UIA tree).

Navigation moves over the live UI Automation tree rooted at
``engine.current_object.native`` (a vendored ``uiautomation.Control``):

    prev     -> previous sibling
    next     -> next sibling
    parent   -> parent
    child    -> first child
    current  -> re-announce the current element
    activate -> Invoke / Select / SetFocus+Enter the current element

Each move rebuilds an :class:`AccessibleObject` for the new element through
``engine.provider.element_to_object`` (falling back to a minimal snapshot),
updates ``engine.current_object`` and announces it via
``engine.announce_object(obj, for_navigation=True)``. Edges play ``edge.ogg``.
"""

from titan_access.contracts import AccessibleObject, SND_EDGE, ROLE_UNKNOWN
from titan_access.localization import L

try:  # vendored uiautomation lib (see data/components/titan access/lib)
    import uiautomation as _auto
except Exception as e:  # pragma: no cover - degrades to "no navigation"
    print(f"[TitanAccess] object_nav: uiautomation unavailable: {e}")
    _auto = None

# UIA control types we treat as a window boundary when walking to a parent: the
# tree above these is the shell/desktop and is not useful to expose.
_BOUNDARY_TYPES = {"WindowControl", "PaneControl"}


class ObjectNavigator:
    """Object navigation over the UIA tree."""

    def __init__(self, engine):
        self.engine = engine

    # ------------------------------------------------------------------ #
    def navigate(self, direction):
        """Perform *direction* navigation. Returns True if handled."""
        native = self._current_native()
        if direction == "current":
            self.engine.announce_object(self.engine.current_object,
                                        for_navigation=False)
            return True
        if direction == "activate":
            return self._activate(native)

        if native is None:
            self.engine.speak(L("engine.noCurrentElement"))
            return True

        target = self._step(native, direction)
        if target is None:
            self.engine.play(SND_EDGE, self.engine.current_object)
            return True

        obj = self._to_object(target)
        if obj is None:
            self.engine.play(SND_EDGE, self.engine.current_object)
            return True

        self.engine.current_object = obj
        self.engine.announce_object(obj, for_navigation=True)
        return True

    # ------------------------------------------------------------------ #
    # Tree stepping
    # ------------------------------------------------------------------ #
    def _step(self, native, direction):
        try:
            if direction == "prev":
                return native.GetPreviousSiblingControl()
            if direction == "next":
                return native.GetNextSiblingControl()
            if direction == "parent":
                parent = native.GetParentControl()
                if parent is not None and self._is_boundary(parent):
                    return None
                return parent
            if direction == "child":
                return native.GetFirstChildControl()
        except Exception as e:
            print(f"[TitanAccess] object_nav: step '{direction}' error: {e}")
        return None

    @staticmethod
    def _is_boundary(element):
        try:
            return element.ControlTypeName in _BOUNDARY_TYPES and not (element.Name or "")
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Activation
    # ------------------------------------------------------------------ #
    def _activate(self, native):
        if native is None:
            self.engine.speak(L("engine.noCurrentElement"))
            return True
        ok = False
        # Try the action patterns in turn (Invoke -> Select -> Expand).
        for getter, call in (("GetInvokePattern", "Invoke"),
                             ("GetSelectionItemPattern", "Select"),
                             ("GetExpandCollapsePattern", "Expand")):
            try:
                pattern = getattr(native, getter)()
            except Exception:
                pattern = None
            if pattern is None:
                continue
            try:
                getattr(pattern, call)()
                ok = True
                break
            except Exception:
                continue
        # Fallback: focus the element and press Enter.
        if not ok:
            try:
                native.SetFocus()
                self._press_enter()
                ok = True
            except Exception:
                ok = False

        if ok:
            try:
                self.engine.refresh_current_scope(delay_ms=450)
            except Exception:
                pass
        else:
            try:
                self.engine.speak(L("engine.cannotActivate"))
            except Exception:
                pass
        return True

    @staticmethod
    def _press_enter():
        try:
            import ctypes
            KEYEVENTF_KEYUP = 0x0002
            VK_RETURN = 0x0D
            ctypes.windll.user32.keybd_event(VK_RETURN, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _current_native(self):
        obj = self.engine.current_object
        native = getattr(obj, "native", None) if obj is not None else None
        if native is not None:
            return native
        # Fall back to whatever currently has focus.
        try:
            if self.engine.provider is not None:
                focused = self.engine.provider.get_focused_object()
                if focused is not None:
                    self.engine.current_object = focused
                    return getattr(focused, "native", None)
        except Exception:
            pass
        return None

    def _to_object(self, element):
        """Build an AccessibleObject for *element* via the provider, with a
        minimal fallback so navigation still works if the provider cannot."""
        provider = getattr(self.engine, "provider", None)
        if provider is not None and hasattr(provider, "element_to_object"):
            try:
                obj = provider.element_to_object(element)
                if obj is not None:
                    return obj
            except Exception as e:
                print(f"[TitanAccess] object_nav: element_to_object error: {e}")
        # Minimal snapshot fallback.
        try:
            name = element.Name or ""
        except Exception:
            name = ""
        return AccessibleObject(name=name, role=ROLE_UNKNOWN, native=element)
