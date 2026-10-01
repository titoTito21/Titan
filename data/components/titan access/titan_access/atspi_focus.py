"""Titan Access on Linux: the focus, read through AT-SPI 2.

On Windows the reader's provider is UI Automation with MSAA behind it. On a
Linux desktop the accessibility tree is AT-SPI 2 - the tree Orca reads -
reached through PyGObject (``gi.repository.Atspi``, package ``python3-gi``
plus ``gir1.2-atspi-2.0``). This provider fills the same
:class:`~titan_access.contracts.AccessibleObject` the UIA one fills, so the
engine's announcement, object navigation, scan mode and gestures are the
same code on both.

What it registers: ``object:state-changed:focused`` (the focus moving) and
``object:state-changed:checked`` / ``expanded`` (a state changing under
the focus). The events arrive on the GLib main loop that
:func:`titan_access.engine.TitanAccessEngine._run` runs on Linux in place
of the Win32 message pump, so ``on_focus`` is already on the engine's
thread, as it is on Windows.
"""
import sys
import time
from typing import Optional

from titan_access import contracts as C
from titan_access.contracts import AccessibleObject

IS_LINUX = sys.platform.startswith('linux')

_Atspi = None
_why = ''


def atspi():
    """The Atspi namespace, or None (and :func:`why_unavailable` says why)."""
    global _Atspi, _why
    if _Atspi is not None:
        return _Atspi
    if not IS_LINUX:
        _why = 'AT-SPI is Linux'
        return None
    try:
        import gi
        gi.require_version('Atspi', '2.0')
        from gi.repository import Atspi
    except Exception as e:                           # noqa: BLE001
        _why = f'python3-gi / gir1.2-atspi-2.0: {e}'
        return None
    _Atspi = Atspi
    return Atspi


def why_unavailable():
    return _why


# --------------------------------------------------------------------------- #
# Roles and states
# --------------------------------------------------------------------------- #
def _role_map(Atspi):
    R = Atspi.Role
    return {
        R.PUSH_BUTTON: C.ROLE_BUTTON, R.TOGGLE_BUTTON: C.ROLE_BUTTON,
        R.TEXT: C.ROLE_EDIT, R.ENTRY: C.ROLE_EDIT, R.PASSWORD_TEXT: C.ROLE_PASSWORD,
        R.DOCUMENT_FRAME: C.ROLE_DOCUMENT, R.DOCUMENT_TEXT: C.ROLE_DOCUMENT,
        R.DOCUMENT_WEB: C.ROLE_DOCUMENT, R.DOCUMENT_EMAIL: C.ROLE_DOCUMENT,
        R.CHECK_BOX: C.ROLE_CHECKBOX, R.CHECK_MENU_ITEM: C.ROLE_MENUITEM,
        R.RADIO_BUTTON: C.ROLE_RADIO, R.RADIO_MENU_ITEM: C.ROLE_MENUITEM,
        R.COMBO_BOX: C.ROLE_COMBOBOX,
        R.LIST: C.ROLE_LISTBOX, R.LIST_BOX: C.ROLE_LISTBOX, R.LIST_ITEM: C.ROLE_LISTITEM,
        R.TREE: C.ROLE_TREE, R.TREE_TABLE: C.ROLE_TREE, R.TREE_ITEM: C.ROLE_TREEITEM,
        R.MENU: C.ROLE_MENU, R.MENU_BAR: C.ROLE_MENUBAR, R.MENU_ITEM: C.ROLE_MENUITEM,
        R.PAGE_TAB: C.ROLE_TAB, R.PAGE_TAB_LIST: C.ROLE_TABCONTROL,
        R.SLIDER: C.ROLE_SLIDER, R.SPIN_BUTTON: C.ROLE_SPINNER,
        R.PROGRESS_BAR: C.ROLE_PROGRESSBAR, R.SCROLL_BAR: C.ROLE_SCROLLBAR,
        R.LINK: C.ROLE_LINK, R.LABEL: C.ROLE_TEXT, R.STATIC: C.ROLE_TEXT,
        R.HEADING: C.ROLE_HEADING, R.IMAGE: C.ROLE_IMAGE, R.ICON: C.ROLE_IMAGE,
        R.TABLE: C.ROLE_TABLE, R.TABLE_ROW: C.ROLE_ROW, R.TABLE_CELL: C.ROLE_CELL,
        R.TABLE_COLUMN_HEADER: C.ROLE_CELL, R.TABLE_ROW_HEADER: C.ROLE_CELL,
        R.TOOL_BAR: C.ROLE_TOOLBAR, R.STATUS_BAR: C.ROLE_STATUSBAR,
        R.PANEL: C.ROLE_PANE, R.FILLER: C.ROLE_PANE, R.SCROLL_PANE: C.ROLE_PANE,
        R.GROUPING: C.ROLE_GROUP, R.DIALOG: C.ROLE_DIALOG, R.ALERT: C.ROLE_DIALOG,
        R.FRAME: C.ROLE_WINDOW, R.WINDOW: C.ROLE_WINDOW, R.SEPARATOR: C.ROLE_SEPARATOR,
        R.APPLICATION: C.ROLE_WINDOW,
    }


_roles = None


def role_of(Atspi, acc):
    global _roles
    if _roles is None:
        _roles = _role_map(Atspi)
    try:
        return _roles.get(acc.get_role(), C.ROLE_UNKNOWN)
    except Exception:                                # noqa: BLE001
        return C.ROLE_UNKNOWN


def states_of(Atspi, acc, role):
    S = Atspi.StateType
    out = set()
    try:
        st = acc.get_state_set()
    except Exception:                                # noqa: BLE001
        return out
    has = st.contains
    if has(S.FOCUSED):
        out.add(C.STATE_FOCUSED)
    if has(S.CHECKABLE) or role in (C.ROLE_CHECKBOX, C.ROLE_RADIO):
        out.add(C.STATE_CHECKED if has(S.CHECKED) else C.STATE_UNCHECKED)
    if has(S.INDETERMINATE):
        out.discard(C.STATE_UNCHECKED)
        out.add(C.STATE_PARTIAL)
    if has(S.EXPANDABLE):
        out.add(C.STATE_EXPANDED if has(S.EXPANDED) else C.STATE_COLLAPSED)
    if has(S.SELECTED):
        out.add(C.STATE_SELECTED)
    if not has(S.ENABLED) or not has(S.SENSITIVE):
        out.add(C.STATE_UNAVAILABLE)
    if role in (C.ROLE_EDIT, C.ROLE_DOCUMENT) and not has(S.EDITABLE):
        out.add(C.STATE_READONLY)
    if has(S.REQUIRED):
        out.add(C.STATE_REQUIRED)
    if has(S.PRESSED):
        out.add(C.STATE_PRESSED)
    if has(S.BUSY):
        out.add(C.STATE_BUSY)
    if has(S.HAS_POPUP):
        out.add(C.STATE_HASPOPUP)
    if role == C.ROLE_PASSWORD:
        out.add(C.STATE_PROTECTED)
    return out


def _value_of(Atspi, acc, role):
    try:
        if role in (C.ROLE_EDIT, C.ROLE_PASSWORD, C.ROLE_DOCUMENT):
            text = acc.get_text_iface() if hasattr(acc, 'get_text_iface') else acc.get_text()
            if text is not None:
                count = text.get_character_count()
                if role == C.ROLE_PASSWORD:
                    return ''
                return text.get_text(0, min(count, 4000)) if count else ''
    except Exception:                                # noqa: BLE001
        pass
    try:
        value = acc.get_value_iface() if hasattr(acc, 'get_value_iface') else acc.get_value()
        if value is not None:
            current = value.get_current_value()
            return ('%g' % current) if current is not None else ''
    except Exception:                                # noqa: BLE001
        pass
    return ''


def _bounds_of(Atspi, acc):
    try:
        comp = acc.get_component_iface() if hasattr(acc, 'get_component_iface') else acc
        rect = comp.get_extents(Atspi.CoordType.SCREEN)
        if rect is None:
            return (0, 0, 0, 0)
        return (int(rect.x), int(rect.y), int(rect.x + rect.width), int(rect.y + rect.height))
    except Exception:                                # noqa: BLE001
        return (0, 0, 0, 0)


_SET_ROLES = (C.ROLE_LISTITEM, C.ROLE_MENUITEM, C.ROLE_TREEITEM, C.ROLE_TAB,
              C.ROLE_ROW, C.ROLE_RADIO, C.ROLE_CELL)


def to_object(acc) -> Optional[AccessibleObject]:
    """One AccessibleObject out of one Atspi.Accessible; None for nothing."""
    Atspi = atspi()
    if Atspi is None or acc is None:
        return None
    try:
        role = role_of(Atspi, acc)
        obj = AccessibleObject(native=acc, provider='atspi')
        obj.role = role
        obj.name = acc.get_name() or ''
        obj.description = acc.get_description() or ''
        obj.value = _value_of(Atspi, acc, role)
        obj.states = states_of(Atspi, acc, role)
        obj.bounds = _bounds_of(Atspi, acc)
        try:
            obj.process_id = int(acc.get_process_id())
        except Exception:                            # noqa: BLE001
            obj.process_id = 0
        if role in _SET_ROLES:
            try:
                parent = acc.get_parent()
                if parent is not None:
                    obj.pos_in_set = int(acc.get_index_in_parent()) + 1
                    obj.size_of_set = int(parent.get_child_count())
            except Exception:                        # noqa: BLE001
                pass
        if role == C.ROLE_TREEITEM:
            obj.level = _tree_level(Atspi, acc)
        if role == C.ROLE_HEADING:
            obj.level = _heading_level(acc)
        try:
            app = acc.get_application()
            obj.class_name = (app.get_name() or '') if app is not None else ''
        except Exception:                            # noqa: BLE001
            pass
        obj.framework_id = 'atspi'
        if role == C.ROLE_LINK:
            obj.parameter = obj.value
        return obj
    except Exception:                                # noqa: BLE001
        return None


def _tree_level(Atspi, acc):
    level, node = 0, acc
    try:
        while node is not None and level < 30:
            node = node.get_parent()
            if node is None:
                break
            if node.get_role() == Atspi.Role.TREE_ITEM:
                level += 1
    except Exception:                                # noqa: BLE001
        pass
    return level + 1 if level else 1


def _heading_level(acc):
    try:
        attrs = acc.get_attributes() or {}
        return int(attrs.get('level', 0) or 0)
    except Exception:                                # noqa: BLE001
        return 0


# --------------------------------------------------------------------------- #
# The provider
# --------------------------------------------------------------------------- #
class AtspiProvider:
    """``AccessibilityProviderLike`` over AT-SPI 2."""

    name = 'atspi'

    def __init__(self):
        self._focus_listeners = []
        self._state_listeners = []
        self._listeners = []          # Atspi.EventListener objects, kept alive
        self._last = None             # (accessible, when)
        self._last_obj = None
        self.started = False

    # -- registration --------------------------------------------------- #
    def add_focus_listener(self, callback):
        self._focus_listeners.append(callback)

    def add_state_listener(self, callback):
        self._state_listeners.append(callback)

    def start(self) -> bool:
        Atspi = atspi()
        if Atspi is None:
            print(f"[TitanAccess] atspi_focus: {_why}")
            return False
        try:
            Atspi.init()
        except Exception:                            # noqa: BLE001
            pass
        for event_name, handler in (('object:state-changed:focused', self._on_focus_event),
                                    ('focus:', self._on_focus_event),
                                    ('object:state-changed:checked', self._on_state_event),
                                    ('object:state-changed:expanded', self._on_state_event),
                                    ('object:state-changed:selected', self._on_state_event)):
            try:
                listener = Atspi.EventListener.new(handler)
                Atspi.EventListener.register(listener, event_name)
                self._listeners.append((listener, event_name))
            except Exception as e:                   # noqa: BLE001
                print(f"[TitanAccess] atspi_focus: cannot listen for {event_name}: {e}")
        self.started = bool(self._listeners)
        return self.started

    def stop(self):
        Atspi = atspi()
        for listener, event_name in self._listeners:
            try:
                Atspi.EventListener.deregister(listener, event_name)
            except Exception:                        # noqa: BLE001
                pass
        self._listeners = []
        self.started = False

    # -- events ----------------------------------------------------------- #
    def _on_focus_event(self, event):
        try:
            if event.type.startswith('object:state-changed') and not event.detail1:
                return                                # focus LEFT this one
            acc = event.source
            if acc is None:
                return
            now = time.time()
            if self._last and self._last[0] == acc and now - self._last[1] < 0.05:
                return                                # the same focus twice
            self._last = (acc, now)
            obj = to_object(acc)
            if obj is None:
                return
            self._last_obj = obj
            for callback in list(self._focus_listeners):
                try:
                    callback(obj)
                except Exception as e:               # noqa: BLE001
                    print(f"[TitanAccess] atspi_focus: focus listener error: {e}")
        except Exception as e:                       # noqa: BLE001
            print(f"[TitanAccess] atspi_focus: focus event error: {e}")

    def _on_state_event(self, event):
        try:
            acc = event.source
            if acc is None or not self._state_listeners:
                return
            if self._last is None or self._last[0] != acc:
                return                                # not the control the user is on
            obj = to_object(acc)
            if obj is None:
                return
            for callback in list(self._state_listeners):
                try:
                    callback(obj)
                except Exception as e:               # noqa: BLE001
                    print(f"[TitanAccess] atspi_focus: state listener error: {e}")
        except Exception:                            # noqa: BLE001
            pass

    # -- questions -------------------------------------------------------- #
    def get_focused_object(self) -> Optional[AccessibleObject]:
        Atspi = atspi()
        if Atspi is None:
            return None
        if self._last is not None:
            obj = to_object(self._last[0])
            if obj is not None:
                return obj
        window = active_window()
        if window is None:
            return None
        found = _find_focused(Atspi, window, 0)
        return to_object(found) if found is not None else to_object(window)

    def element_to_object(self, element):
        return to_object(element)

    def object_from_point(self, x, y) -> Optional[AccessibleObject]:
        Atspi = atspi()
        window = active_window()
        if Atspi is None or window is None:
            return None
        try:
            comp = window.get_component_iface() if hasattr(window, 'get_component_iface') else window
            acc = comp.get_accessible_at_point(int(x), int(y), Atspi.CoordType.SCREEN)
            return to_object(acc) if acc is not None else None
        except Exception:                            # noqa: BLE001
            return None

    def object_from_handle(self, hwnd) -> Optional[AccessibleObject]:
        window = active_window()
        return to_object(window) if window is not None else None


def _find_focused(Atspi, node, depth):
    if depth > 25:
        return None
    try:
        if node.get_state_set().contains(Atspi.StateType.FOCUSED):
            return node
        for i in range(min(node.get_child_count(), 500)):
            child = node.get_child_at_index(i)
            if child is None:
                continue
            found = _find_focused(Atspi, child, depth + 1)
            if found is not None:
                return found
    except Exception:                                # noqa: BLE001
        return None
    return None


def active_window():
    """The window in front, as an Atspi.Accessible, or None.

    ACTIVE where the compositor sets it; the last SHOWING window otherwise
    (WSLg's Weston does not set ACTIVE reliably).
    """
    Atspi = atspi()
    if Atspi is None:
        return None
    showing = None
    try:
        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app is None:
                continue
            for j in range(app.get_child_count()):
                window = app.get_child_at_index(j)
                if window is None:
                    continue
                states = window.get_state_set()
                if states.contains(Atspi.StateType.ACTIVE):
                    return window
                if states.contains(Atspi.StateType.SHOWING) and window.get_name():
                    showing = window
    except Exception:                                # noqa: BLE001
        return showing
    return showing


def window_title(window=None):
    window = window or active_window()
    try:
        return (window.get_name() or '') if window is not None else ''
    except Exception:                                # noqa: BLE001
        return ''
