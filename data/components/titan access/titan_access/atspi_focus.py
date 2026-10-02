"""Titan Access on Linux: the focus, read through AT-SPI 2.

On Windows the reader's provider is UI Automation with MSAA behind it. On a
Linux desktop the accessibility tree is AT-SPI 2 - the tree Orca reads -
reached through PyGObject (``gi.repository.Atspi``, package ``python3-gi``
plus ``gir1.2-atspi-2.0``). This provider fills the same
:class:`~titan_access.contracts.AccessibleObject` the UIA one fills, so the
engine's announcement, object navigation, scan mode and gestures are the
same code on both.

What it registers: ``object:state-changed:focused`` (the focus moving),
``object:state-changed:checked`` / ``expanded`` (a state changing under
the focus) - and the three ways a GTK toolkit says "the cursor is on a
different ROW" without moving the focus at all, measured on a wx window
in WSLg: a list row is ``object:selection-changed`` on the table (the
focus stays on the table; the cell gets no focus event of its own), a
menu opening is ``object:state-changed:selected`` on the menu and
``object:selection-changed`` on the menu bar, and a row the toolkit
does report is ``object:active-descendant-changed`` carrying the child.
Each is turned into the same focus callback the UIA provider makes, so
the engine announces a row, a menu item or a tab the way it announces a
button. The events arrive on the GLib main loop that
:func:`titan_access.engine.TitanAccessEngine._run_posix` runs on a
context of the reader's own, so ``on_focus`` is on the engine's thread,
as it is on Windows.
"""
import os
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
        # Nautilus' icon view: a LAYERED_PANE of CANVAS items, one per file,
        # each focusable and named - a list of rows to the user.
        R.LAYERED_PANE: C.ROLE_PANE, R.CANVAS: C.ROLE_LISTITEM,
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


_UNAVAILABLE_ROLES = (C.ROLE_BUTTON, C.ROLE_MENUITEM, C.ROLE_CHECKBOX, C.ROLE_RADIO,
                      C.ROLE_EDIT, C.ROLE_PASSWORD, C.ROLE_COMBOBOX, C.ROLE_SLIDER,
                      C.ROLE_SPINNER, C.ROLE_LINK, C.ROLE_TAB, C.ROLE_MENU, C.ROLE_DOCUMENT)


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
    # Nautilus' canvas items carry neither ENABLED nor SENSITIVE and are
    # perfectly usable; "unavailable" is claimed only of a control that
    # would say so honestly - a greyed button, menu item or field.
    if (not has(S.ENABLED) or not has(S.SENSITIVE)) and role in _UNAVAILABLE_ROLES:
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
        if not obj.name.strip() and obj.description.strip() and role not in (
                C.ROLE_EDIT, C.ROLE_DOCUMENT, C.ROLE_PASSWORD, C.ROLE_TEXT):
            # GTK names an icon button and a sidebar row by their
            # DESCRIPTION (the tooltip): "Open your personal folder",
            # "Recent files". A reader that reads only the name says
            # "button" for each of them.
            obj.name = obj.description.strip()
        obj.value = _value_of(Atspi, acc, role)
        obj.states = states_of(Atspi, acc, role)
        obj.bounds = _bounds_of(Atspi, acc)
        try:
            obj.process_id = int(acc.get_process_id())
        except Exception:                            # noqa: BLE001
            obj.process_id = 0
        if role == C.ROLE_CELL:
            # A wx list on GTK is a GtkTreeView, which ATK reports as a
            # TABLE of TABLE_CELLs - a cell of a one-column table is a list
            # item to the user and is called one.
            # <= 1: a GtkTreeView being rebuilt answers 0 columns for a
            # moment, and a cell of it is still a row of a list.
            if _table_columns(Atspi, acc) <= 1:
                role = obj.role = C.ROLE_LISTITEM
        if role in _SET_ROLES:
            obj.pos_in_set, obj.size_of_set = _position_in_set(Atspi, acc)
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


def _table_of(acc):
    """The TABLE / TREE_TABLE a cell sits in (its parent, or its row's), or None."""
    try:
        parent = acc.get_parent()
        if parent is None:
            return None
        Atspi = atspi()
        if parent.get_role() == Atspi.Role.TABLE_ROW:
            parent = parent.get_parent()
        if parent is not None and parent.get_role() in (Atspi.Role.TABLE, Atspi.Role.TREE_TABLE):
            return parent
    except Exception:                                # noqa: BLE001
        pass
    return None


def _table_columns(Atspi, acc):
    table = _table_of(acc)
    if table is None:
        return 0
    try:
        t = table.get_table_iface() if hasattr(table, 'get_table_iface') else table
        return int(t.get_n_columns()) if t is not None else 0
    except Exception:                                # noqa: BLE001
        return 0


def _position_in_set(Atspi, acc):
    """(position, count) of *acc* among its peers: for a cell, its ROW
    among the table's rows (a GtkTreeView's first child is the column
    header, so the first row used to be "2 of 10"); for anything else, its
    index among the siblings of the same role."""
    try:
        parent = acc.get_parent()
        if parent is None:
            return (0, 0)
        table = _table_of(acc)
        if table is not None:
            try:
                t = table.get_table_iface() if hasattr(table, 'get_table_iface') else table
                rows = int(t.get_n_rows())
                row = int(t.get_row_at_index(int(acc.get_index_in_parent())))
                if rows > 0 and row >= 0:
                    return (row + 1, rows)
            except Exception:                        # noqa: BLE001
                pass
        role = acc.get_role()
        skip = (Atspi.Role.TABLE_COLUMN_HEADER, Atspi.Role.TABLE_ROW_HEADER,
                Atspi.Role.SEPARATOR)
        count, position = 0, 0
        me = int(acc.get_index_in_parent())
        for i in range(min(int(parent.get_child_count()), 2000)):
            child = parent.get_child_at_index(i)
            if child is None:
                continue
            crole = child.get_role()
            if crole in skip or (role not in skip and crole != role and role != Atspi.Role.MENU_ITEM):
                continue
            count += 1
            if i == me:
                position = count
        return (position, count) if position else (me + 1, int(parent.get_child_count()))
    except Exception:                                # noqa: BLE001
        return (0, 0)


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

    # A selection change inside one of these says where the cursor is.
    _SELECTION_ROLES = None   # filled on first use (needs Atspi)

    def __init__(self):
        self._focus_listeners = []
        self._state_listeners = []
        self._listeners = []          # Atspi.EventListener objects, kept alive
        self._last = None             # (accessible, when)
        self._last_key = None         # (path key, when) - the row said last
        self._last_obj = None
        self.started = False
        self.wrong_thread_events = 0  # events dispatched off the reader's thread
        self._thread_ident = None
        # Set by the engine: runs a callable on the reader's thread. libatspi
        # DEFERS every incoming message and processes the queue from
        # whichever thread next makes a libatspi call (or its idle source),
        # so an event can arrive on any thread that touched the bus; one
        # that did is handed back to the reader's own rather than handled
        # where it landed.
        self.marshal = None
        # Set by the engine: re-attaches every AT-SPI connection to the
        # reader's context. An application's DIRECT connection is opened
        # by libatspi on first contact, on the default context whatever
        # was pinned, and the ATK bridge sends its events down that
        # connection too - so the first event from a newly met program
        # arrives on the main thread, and the fix is to pin again then.
        self.repin = None
        self._repinned_at = 0.0

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
        import threading
        self._thread_ident = threading.get_ident()
        for event_name, handler in (('object:state-changed:focused', self._on_focus_event),
                                    ('focus:', self._on_focus_event),
                                    ('object:state-changed:selected', self._on_selected_event),
                                    ('object:selection-changed', self._on_selection_event),
                                    ('object:active-descendant-changed', self._on_descendant_event),
                                    ('object:state-changed:checked', self._on_state_event),
                                    ('object:state-changed:expanded', self._on_state_event)):
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
    def _on_wrong_thread(self, event, handler):
        """True when *event* arrived off the reader's thread and was handed
        to it; the caller then returns at once."""
        if not self._note_thread(event):
            return False
        marshal = self.marshal
        if marshal is None:
            return False                              # handle it here, then
        repin = self.repin
        now = time.time()
        if repin is not None and now - self._repinned_at > 1.0:
            self._repinned_at = now

            def _then():
                try:
                    repin()
                except Exception:                    # noqa: BLE001
                    pass
                handler(event)
            job = _then
        else:
            job = lambda: handler(event)              # noqa: E731
        try:
            marshal(job)
            return True
        except Exception:                            # noqa: BLE001
            return False

    def _note_thread(self, event=None):
        """Count an event that arrived on a thread that is not the reader's.
        libatspi 2.38 attaches an application's direct connection to the
        DEFAULT GLib context whatever ``set_main_context`` was told, so
        this is how a wrong attachment is noticed (it is re-pinned by the
        engine) rather than guessed at. The first few are named, so a
        re-pin that does not take can be read about."""
        import threading
        if self._thread_ident and threading.get_ident() != self._thread_ident:
            self.wrong_thread_events += 1
            if self.wrong_thread_events <= 4 and event is not None:
                try:
                    src = event.source
                    print(f"[TitanAccess] atspi_focus: {event.type} arrived on thread "
                          f"{threading.current_thread().name} from "
                          f"{(src.get_application().get_name() if src is not None and src.get_application() is not None else '?')}")
                    if os.environ.get('TITAN_ACCESS_TRACE') and self.wrong_thread_events == 1:
                        # Who on that thread called into libatspi (its
                        # deferred queue is drained after any call).
                        import traceback
                        print("[TitanAccess] atspi_focus: that thread's stack:\n"
                              + "".join(traceback.format_stack(limit=12)))
                except Exception:                    # noqa: BLE001
                    pass
            return True
        return False

    def _deliver(self, acc, why=''):
        """Announce *acc* as the focus, once: a row said twice is the
        ``selected`` event and the ``selection-changed`` event of the same
        arrow key, which arrive a millisecond apart."""
        if acc is None:
            return
        now = time.time()
        key = path_key(acc)
        if self._last_key and self._last_key[0] == key and now - self._last_key[1] < 0.3:
            return
        self._last_key = (key, now)
        self._last = (acc, now)
        obj = to_object(acc)
        if obj is None:
            return
        self._last_obj = obj
        for callback in list(self._focus_listeners):
            try:
                callback(obj)
            except Exception as e:               # noqa: BLE001
                print(f"[TitanAccess] atspi_focus: focus listener error ({why}): {e}")

    def _on_focus_event(self, event):
        try:
            if self._on_wrong_thread(event, self._on_focus_event):
                return
            if event.type.startswith('object:state-changed') and not event.detail1:
                return                                # focus LEFT this one
            acc = event.source
            if acc is None:
                return
            # A container that has just taken the focus is read as the ROW
            # the cursor is on, as a reader does for a list: the toolkit
            # says the table is focused and says nothing about the cell.
            row = selected_child(acc)
            self._deliver(row if row is not None else acc, 'focus')
        except Exception as e:                       # noqa: BLE001
            print(f"[TitanAccess] atspi_focus: focus event error: {e}")

    def _on_selected_event(self, event):
        """``object:state-changed:selected`` on an item: a menu opening, a
        menu item or a row the cursor moved onto."""
        try:
            if self._on_wrong_thread(event, self._on_selected_event):
                return
            if not event.detail1:
                return
            acc = event.source
            if acc is None:
                return
            Atspi = atspi()
            role = acc.get_role()
            if role in (Atspi.Role.MENU, Atspi.Role.MENU_ITEM, Atspi.Role.CHECK_MENU_ITEM,
                        Atspi.Role.RADIO_MENU_ITEM):
                # A nameless MENU is the dropdown itself opening under its
                # entry (GTK selects it before the first item); the item's
                # own event follows and is the one worth saying.
                if role == Atspi.Role.MENU and not (acc.get_name() or '').strip():
                    return
                self._deliver(acc, 'selected')
                return
            if role in self._selection_roles(Atspi) and container_has_focus(acc):
                self._deliver(acc, 'selected')
        except Exception as e:                       # noqa: BLE001
            print(f"[TitanAccess] atspi_focus: selected event error: {e}")

    def _on_selection_event(self, event):
        """``object:selection-changed`` on a container: the newly selected
        child is the row. Only a container that has the keyboard (or is a
        menu) - a status bar re-selecting its clock every second is not
        the user moving."""
        try:
            if self._on_wrong_thread(event, self._on_selection_event):
                return
            acc = event.source
            if acc is None:
                return
            Atspi = atspi()
            role = acc.get_role()
            if role not in (Atspi.Role.MENU_BAR, Atspi.Role.MENU) and not _has_state(Atspi, acc, Atspi.StateType.FOCUSED):
                return
            child = selected_child(acc)
            if child is None:
                return
            # The row the reader said last, selected again: a list that
            # refreshes itself re-selects its row every few seconds, and
            # that is not the user moving. A different row is.
            if self._last_key and self._last_key[0] == path_key(child):
                return
            self._deliver(child, 'selection')
        except Exception as e:                       # noqa: BLE001
            print(f"[TitanAccess] atspi_focus: selection event error: {e}")

    def _on_descendant_event(self, event):
        try:
            if self._on_wrong_thread(event, self._on_descendant_event):
                return
            child = event.any_data
            if child is None or not hasattr(child, 'get_role'):
                return
            self._deliver(child, 'descendant')
        except Exception as e:                       # noqa: BLE001
            print(f"[TitanAccess] atspi_focus: descendant event error: {e}")

    def _selection_roles(self, Atspi):
        if AtspiProvider._SELECTION_ROLES is None:
            R = Atspi.Role
            AtspiProvider._SELECTION_ROLES = {
                R.LIST_ITEM, R.TABLE_CELL, R.TABLE_ROW, R.TREE_ITEM, R.PAGE_TAB,
                R.RADIO_BUTTON, R.TABLE_COLUMN_HEADER}
        return AtspiProvider._SELECTION_ROLES

    def _on_state_event(self, event):
        try:
            if self._on_wrong_thread(event, self._on_state_event):
                return
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
        # A bounded look for the focused control - not a walk of every
        # node in the window (25 levels of 500) made of one blocking call
        # each, which at start-up ran for seconds against a window the
        # main thread was rebuilding, and ended in a segmentation fault
        # inside libatspi. The focus event will say where the focus is
        # the moment it moves; this is only the first word.
        found = _find_focused(Atspi, window, 0, budget=[160])
        if found is not None:
            row = selected_child(found)
            found = row if row is not None else found
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


def _has_state(Atspi, acc, state):
    try:
        return bool(acc.get_state_set().contains(state))
    except Exception:                                # noqa: BLE001
        return False


def container_has_focus(acc, depth=6):
    """Whether *acc* or an ancestor within *depth* has the FOCUSED state -
    a selected cell belongs to the user when its table has the keyboard."""
    Atspi = atspi()
    if Atspi is None:
        return False
    node = acc
    try:
        for _ in range(depth):
            if node is None:
                return False
            if _has_state(Atspi, node, Atspi.StateType.FOCUSED):
                return True
            node = node.get_parent()
    except Exception:                                # noqa: BLE001
        return False
    return False


def selected_child(acc):
    """The selected child of a container that has a selection - the row the
    cursor is on in a list, table, tree or menu bar - or None. A menu's
    own selected item counts; anything else answers None rather than the
    container's first child."""
    Atspi = atspi()
    if Atspi is None or acc is None:
        return None
    try:
        role = acc.get_role()
    except Exception:                                # noqa: BLE001
        return None
    R = Atspi.Role
    if role not in (R.LIST, R.LIST_BOX, R.TABLE, R.TREE, R.TREE_TABLE, R.MENU_BAR,
                    R.MENU, R.PAGE_TAB_LIST, R.COMBO_BOX):
        return None
    try:
        sel = acc.get_selection_iface() if hasattr(acc, 'get_selection_iface') else acc
        if sel is None:
            return None
        if int(sel.get_n_selected_children()) < 1:
            return None
        child = sel.get_selected_child(0)
    except Exception:                                # noqa: BLE001
        return None
    if child is None:
        return None
    try:
        # A table answers the whole ROW's first cell; the row's name is what
        # is read. A selected child that is itself a container with a
        # selection (a tree row holding cells) is followed one level down.
        inner = selected_child(child) if child.get_role() in (R.TABLE_ROW,) else None
        return inner if inner is not None else child
    except Exception:                                # noqa: BLE001
        return child


def path_key(acc, depth=12):
    """A stable identity for *acc* - its role and index at each level up
    to the application - for telling one event apart from the same row's
    second event. Two Atspi wrappers for one object need not be equal."""
    parts = []
    node = acc
    try:
        for _ in range(depth):
            if node is None:
                break
            parts.append((int(node.get_role()), int(node.get_index_in_parent())))
            node = node.get_parent()
    except Exception:                                # noqa: BLE001
        pass
    return tuple(parts)


def ancestors(acc, depth=14):
    """*acc* and its parents, nearest first, up to *depth*."""
    out = []
    node = acc
    try:
        for _ in range(depth):
            if node is None:
                break
            out.append(node)
            node = node.get_parent()
    except Exception:                                # noqa: BLE001
        pass
    return out


def pin_main_context(ctx):
    """Attach every AT-SPI connection to *ctx*, and only *ctx*.

    ``Atspi.set_main_context`` re-attaches the a11y bus and every known
    application's direct connection - but returns at once when told the
    context it already has, and libatspi 2.38 attaches a NEW application's
    direct connection to the default context regardless. Setting a throwaway
    context first makes the second call do its whole job again, which is
    what re-pins a connection opened since."""
    Atspi = atspi()
    if Atspi is None or ctx is None:
        return False
    try:
        from gi.repository import GLib
        Atspi.set_main_context(GLib.MainContext())
        Atspi.set_main_context(ctx)
        return True
    except Exception as e:                           # noqa: BLE001
        print(f"[TitanAccess] atspi_focus: cannot pin the main context: {e}")
        return False


def _find_focused(Atspi, node, depth, budget=None):
    if budget is None:
        budget = [2000]
    if depth > 12 or budget[0] <= 0:
        return None
    budget[0] -= 1
    try:
        if node.get_state_set().contains(Atspi.StateType.FOCUSED):
            return node
        for i in range(min(node.get_child_count(), 80)):
            if budget[0] <= 0:
                return None
            child = node.get_child_at_index(i)
            if child is None:
                continue
            found = _find_focused(Atspi, child, depth + 1, budget)
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
        count = desktop.get_child_count()
        if not count:
            # libatspi DEFERS the registry's AddAccessible signals and
            # processes them after a call, so a freshly started client's
            # first answer is "no applications": ask once more.
            desktop.get_name()
            count = desktop.get_child_count()
        for i in range(count):
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
    except Exception as e:                           # noqa: BLE001
        if os.environ.get('TITAN_ACCESS_TRACE'):
            print(f"[TitanAccess] atspi_focus: active_window: {e}")
        return showing
    return showing


def window_title(window=None):
    window = window or active_window()
    try:
        return (window.get_name() or '') if window is not None else ''
    except Exception:                                # noqa: BLE001
        return ''


# --------------------------------------------------------------------------- #
# The tree, for object navigation and the walked lists
# --------------------------------------------------------------------------- #
def is_accessible(native):
    """Whether *native* is an Atspi.Accessible rather than a UIA control."""
    return native is not None and hasattr(native, 'get_role') and not hasattr(native, 'ControlTypeName')


def children_of(acc, limit=400):
    out = []
    try:
        for i in range(min(int(acc.get_child_count()), limit)):
            child = acc.get_child_at_index(i)
            if child is not None:
                out.append(child)
    except Exception:                                # noqa: BLE001
        pass
    return out


def parent_of(acc):
    try:
        parent = acc.get_parent()
    except Exception:                                # noqa: BLE001
        return None
    if parent is None:
        return None
    try:
        if parent.get_role() in (atspi().Role.APPLICATION, atspi().Role.DESKTOP_FRAME):
            return None                               # the top of what a user walks
    except Exception:                                # noqa: BLE001
        pass
    return parent


def index_of(acc, parent=None):
    """*acc*'s index among its parent's children, or -1. GTK answers -1
    from ``get_index_in_parent`` for some objects (a text view inside a
    scrolled window), and "index -1 plus one" is the object itself - the
    children are then compared by role, name and place."""
    try:
        index = int(acc.get_index_in_parent())
    except Exception:                                # noqa: BLE001
        index = -1
    if index >= 0:
        return index
    try:
        parent = parent or acc.get_parent()
        if parent is None:
            return -1
        count = min(int(parent.get_child_count()), 2000)
        # libatspi keeps one AtspiAccessible per object, so the same child
        # comes back as the same wrapper: identity first.
        for i in range(count):
            child = parent.get_child_at_index(i)
            if child is acc or child == acc:
                return i
        me = (acc.get_role(), acc.get_name() or '', _bounds_of(atspi(), acc))
        for i in range(count):
            child = parent.get_child_at_index(i)
            if child is None:
                continue
            if (child.get_role(), child.get_name() or '', _bounds_of(atspi(), child)) == me:
                return i
    except Exception:                                # noqa: BLE001
        pass
    return -1


def sibling_of(acc, delta):
    try:
        parent = acc.get_parent()
        if parent is None:
            return None
        index = index_of(acc, parent)
        if index < 0:
            return None
        index += delta
        if index < 0 or index >= int(parent.get_child_count()):
            return None
        return parent.get_child_at_index(index)
    except Exception:                                # noqa: BLE001
        return None


def first_child_of(acc, last=False):
    try:
        count = int(acc.get_child_count())
        if count <= 0:
            return None
        return acc.get_child_at_index(count - 1 if last else 0)
    except Exception:                                # noqa: BLE001
        return None


_LAYOUT_ROLES = None


def is_layout(acc):
    """NVDA's "simple review" question: a container that is only layout
    (a nameless panel, filler, scroll pane, viewport, window) is stepped
    over, a control the user can act on or read is landed on."""
    Atspi = atspi()
    global _LAYOUT_ROLES
    if _LAYOUT_ROLES is None:
        R = Atspi.Role
        _LAYOUT_ROLES = {R.PANEL, R.FILLER, R.SCROLL_PANE, R.VIEWPORT, R.FRAME,
                         R.WINDOW, R.DIALOG, R.ALERT, R.SPLIT_PANE, R.LAYERED_PANE,
                         R.ROOT_PANE, R.GLASS_PANE, R.INTERNAL_FRAME, R.GROUPING,
                         R.TOOL_TIP, R.SEPARATOR, R.SCROLL_BAR, R.UNKNOWN,
                         R.TABLE_ROW, R.INVALID}
    try:
        role = acc.get_role()
        if role in _LAYOUT_ROLES:
            # A named group, and a window with a title, are places a user
            # knows by name: the parent of the last control in a dialog is
            # the dialog, not the application.
            if role in (Atspi.Role.GROUPING, Atspi.Role.PANEL, Atspi.Role.FRAME,
                        Atspi.Role.WINDOW, Atspi.Role.DIALOG, Atspi.Role.ALERT) \
                    and (acc.get_name() or '').strip():
                return False
            return True
        st = acc.get_state_set()
        if not st.contains(Atspi.StateType.SHOWING) and not st.contains(Atspi.StateType.VISIBLE):
            return True
        if role in (Atspi.Role.LABEL, Atspi.Role.STATIC) and not (acc.get_name() or '').strip():
            return True
    except Exception:                                # noqa: BLE001
        return True
    return False


def simple_step(acc, direction, budget=600):
    """The next thing a user would want to land on, NVDA's simple review:
    'next' / 'prev' flatten the tree past layout containers, 'parent' is
    the nearest ancestor that is not layout, 'child' the first content
    descendant. None at an edge."""
    if acc is None:
        return None
    if direction == 'parent':
        node = parent_of(acc)
        guard = 0
        while node is not None and guard < 64 and is_layout(node):
            node = parent_of(node)
            guard += 1
        return node
    if direction == 'child':
        child = first_child_of(acc)
        if child is None:
            return None
        return child if not is_layout(child) else _descend(child, False, [budget])
    return _flat_step(acc, direction == 'prev', [budget])


def _descend(node, backward, budget):
    """The first content node inside *node* (its last when *backward*)."""
    while node is not None and budget[0] > 0:
        budget[0] -= 1
        if not is_layout(node):
            return node
        node = first_child_of(node, last=backward)
    return None


def _flat_step(acc, backward, budget):
    node = acc
    delta = -1 if backward else 1
    while node is not None and budget[0] > 0:
        budget[0] -= 1
        seen = {path_key(node)}
        sibling = sibling_of(node, delta)
        while sibling is not None and budget[0] > 0:
            budget[0] -= 1
            key = path_key(sibling)
            if key in seen:
                break                                 # two siblings that look alike
            seen.add(key)
            if not is_layout(sibling):
                return sibling
            inner = _descend(sibling, backward, budget)
            if inner is not None:
                return inner
            sibling = sibling_of(sibling, delta)
        node = parent_of(node)
    return None


def raw_step(acc, direction):
    """A step through the tree as it is, layout and all."""
    if direction == 'prev':
        return sibling_of(acc, -1)
    if direction == 'next':
        return sibling_of(acc, 1)
    if direction == 'parent':
        return parent_of(acc)
    if direction == 'child':
        return first_child_of(acc)
    return None


def is_top(acc):
    try:
        R = atspi().Role
        return acc.get_role() in (R.FRAME, R.WINDOW, R.DIALOG, R.APPLICATION, R.DESKTOP_FRAME)
    except Exception:                                # noqa: BLE001
        return False


_ACTION_NAMES = ('click', 'press', 'activate', 'toggle', 'jump', 'select',
                 'expand or contract', 'expand', 'invoke', 'edit')


def default_action(acc):
    """The name of the action *acc* would take, or ''."""
    try:
        action = acc.get_action_iface() if hasattr(acc, 'get_action_iface') else acc
        if action is None:
            return ''
        n = int(action.get_n_actions())
        names = [(action.get_action_name(i) or '').lower() for i in range(n)]
        for wanted in _ACTION_NAMES:
            if wanted in names:
                return wanted
        return names[0] if names else ''
    except Exception:                                # noqa: BLE001
        return ''


def do_default_action(acc):
    """Press *acc* the way Enter would: its own action first, else the
    focus and a Return key sent through the bus. False when nothing took."""
    try:
        action = acc.get_action_iface() if hasattr(acc, 'get_action_iface') else acc
        if action is not None:
            n = int(action.get_n_actions())
            names = [(action.get_action_name(i) or '').lower() for i in range(n)]
            for wanted in _ACTION_NAMES:
                if wanted in names:
                    return bool(action.do_action(names.index(wanted)))
            if n:
                return bool(action.do_action(0))
    except Exception:                                # noqa: BLE001
        pass
    if not grab_focus(acc):
        return False
    return press_key(0xff0d)                         # Return


def grab_focus(acc):
    try:
        comp = acc.get_component_iface() if hasattr(acc, 'get_component_iface') else acc
        return bool(comp.grab_focus())
    except Exception:                                # noqa: BLE001
        return False


def press_key(keysym):
    """One key, pressed and released, through the registry (XTEST)."""
    Atspi = atspi()
    try:
        Atspi.generate_keyboard_event(int(keysym), None, Atspi.KeySynthType.SYM)
        return True
    except Exception:                                # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Text, for the caret and the review cursor
# --------------------------------------------------------------------------- #
class TextOf:
    """The Atspi.Text interface of a control, with the three questions the
    editable-text handler asks: where the caret is, what the character /
    word / line at an offset is, and the selection."""

    def __init__(self, acc):
        self.acc = acc
        self.text = acc.get_text_iface() if hasattr(acc, 'get_text_iface') else acc

    @classmethod
    def of(cls, acc):
        if acc is None:
            return None
        try:
            t = acc.get_text_iface() if hasattr(acc, 'get_text_iface') else acc
            if t is None:
                return None
            t.get_character_count()
            return cls(acc)
        except Exception:                            # noqa: BLE001
            return None

    def length(self):
        try:
            return int(self.text.get_character_count())
        except Exception:                            # noqa: BLE001
            return 0

    def caret(self):
        try:
            return int(self.text.get_caret_offset())
        except Exception:                            # noqa: BLE001
            return -1

    def set_caret(self, offset):
        try:
            return bool(self.text.set_caret_offset(int(offset)))
        except Exception:                            # noqa: BLE001
            return False

    def unit(self, offset, kind):
        """``(text, start, end)`` of the char / word / line at *offset*."""
        Atspi = atspi()
        gran = {'char': Atspi.TextGranularity.CHAR, 'word': Atspi.TextGranularity.WORD,
                'line': Atspi.TextGranularity.LINE}[kind]
        offset = max(0, min(int(offset), max(0, self.length() - (1 if kind == 'char' else 0))))
        try:
            rng = self.text.get_string_at_offset(offset, gran)
            if rng is not None:
                return (rng.content or '', int(rng.start_offset), int(rng.end_offset))
        except Exception:                            # noqa: BLE001
            pass
        try:
            boundary = {'char': Atspi.TextBoundaryType.CHAR,
                        'word': Atspi.TextBoundaryType.WORD_START,
                        'line': Atspi.TextBoundaryType.LINE_START}[kind]
            rng = self.text.get_text_at_offset(offset, boundary)
            if rng is not None:
                return (rng.content or '', int(rng.start_offset), int(rng.end_offset))
        except Exception:                            # noqa: BLE001
            pass
        if kind == 'char':
            try:
                return (self.text.get_text(offset, offset + 1) or '', offset, offset + 1)
            except Exception:                        # noqa: BLE001
                pass
        return ('', offset, offset)

    def selection(self):
        try:
            if int(self.text.get_n_selections()) < 1:
                return ''
            sel = self.text.get_selection(0)
            if sel is None or int(sel.end_offset) <= int(sel.start_offset):
                return ''
            return self.text.get_text(int(sel.start_offset), int(sel.end_offset)) or ''
        except Exception:                            # noqa: BLE001
            return ''

    def all(self, limit=20000):
        try:
            return self.text.get_text(0, min(self.length(), limit)) or ''
        except Exception:                            # noqa: BLE001
            return ''
