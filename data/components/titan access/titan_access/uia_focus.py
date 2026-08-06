# -*- coding: utf-8 -*-
"""UI Automation provider for Titan Access.

Python port of the C# ``Accessibility/Providers/UIAutomationProvider.cs`` (plus
the bits of ``AccessibilityProviderManager`` that matter to a single-provider
setup). It is the primary accessibility backend: it turns the live Microsoft UI
Automation tree into provider-agnostic :class:`~titan_access.contracts.Accessible
Object` snapshots and pushes a fresh snapshot to the engine on every focus
change.

Two layers of COM are used here, deliberately:

* **Focus events** go through *raw* ``comtypes`` against the
  ``IUIAutomation`` / ``IUIAutomationFocusChangedEventHandler`` interfaces
  generated from ``UIAutomationCore.dll``. The vendored ``uiautomation`` package
  is polling-only and cannot deliver real focus events, so we register our own
  ``COMObject`` handler with ``IUIAutomation.AddFocusChangedEventHandler``.
* **Element reading** reuses the vendored ``uiautomation`` package
  (``lib/uiautomation``) for its convenient ``Control`` wrapper and pattern
  helpers. The raw element pointer delivered by the event (or returned by
  ``GetFocusedElement``) is wrapped with ``Control.CreateControlFromElement``.

The focus callback arrives on an internal UIA thread, so it is kept short and is
fully guarded; it just builds the snapshot and fans it out to the registered
listeners (the engine marshals further work onto its own message-pump thread).

Everything COM-related is wrapped so the module imports even when COM cannot be
initialised; in that degraded state :meth:`UIAProvider.start` returns ``False``
and the engine treats the provider as unavailable.
"""

import ctypes
import os
import sys
import threading
from typing import List, Optional

from titan_access.contracts import (
    AccessibleObject, FocusCallback,
    ROLE_BUTTON, ROLE_SPLIT_BUTTON, ROLE_EDIT, ROLE_PASSWORD, ROLE_DOCUMENT,
    ROLE_CHECKBOX, ROLE_RADIO, ROLE_COMBOBOX, ROLE_LISTBOX, ROLE_LISTITEM,
    ROLE_TREE, ROLE_TREEITEM, ROLE_MENU, ROLE_MENUBAR, ROLE_MENUITEM,
    ROLE_TAB, ROLE_TABCONTROL, ROLE_SLIDER, ROLE_SPINNER, ROLE_PROGRESSBAR,
    ROLE_SCROLLBAR, ROLE_LINK, ROLE_TEXT, ROLE_HEADING, ROLE_IMAGE, ROLE_TABLE,
    ROLE_CELL, ROLE_TOOLBAR, ROLE_STATUSBAR, ROLE_GROUP, ROLE_WINDOW, ROLE_PANE,
    ROLE_SEPARATOR, ROLE_GRID, ROLE_GRIDITEM, ROLE_UNKNOWN,
    STATE_CHECKED, STATE_PARTIAL, STATE_EXPANDED, STATE_COLLAPSED,
    STATE_SELECTED, STATE_UNAVAILABLE, STATE_FOCUSED, STATE_READONLY,
    STATE_REQUIRED, STATE_PROTECTED,
)

# Offscreen has no dedicated constant in contracts (it is a UIA-only nicety), but
# localization.state_label() understands the literal "offscreen" key.
_STATE_OFFSCREEN = "offscreen"


# --------------------------------------------------------------------------- #
# Optional COM / vendored-library imports (degrade gracefully)
# --------------------------------------------------------------------------- #
# The vendored ``uiautomation`` package lives in ``<component>/lib``; make sure
# that directory is importable before we try to load it.
_LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

try:
    import comtypes
    import comtypes.client
    _COMTYPES_OK = True
except Exception as e:  # pragma: no cover - COM not available
    print(f"[TitanAccess] comtypes unavailable: {e}")
    comtypes = None
    _COMTYPES_OK = False

try:
    import uiautomation as _auto  # vendored helper for element reading
    _UIA_LIB_OK = True
except Exception as e:  # pragma: no cover - vendored lib not importable
    print(f"[TitanAccess] uiautomation library unavailable: {e}")
    _auto = None
    _UIA_LIB_OK = False

# Bulk (cached) property reads. Every field below used to be its own
# cross-process call - about thirty per focus change, which is what made focus
# announcements lag in UWP apps and in anything Chromium. See uia_cache.
try:
    from titan_access import uia_cache as _cache
except Exception as e:  # pragma: no cover
    print(f"[TitanAccess] uia_cache unavailable: {e}")
    _cache = None


# CLSIDs for the UI Automation root objects.
_CLSID_CUIAUTOMATION8 = "{e22ad333-b25f-460c-83d0-0581107395c9}"
_CLSID_CUIAUTOMATION = "{ff48dba4-60ef-4201-aa87-54103eef594e}"

# COINIT_APARTMENTTHREADED; benign return codes (already initialised / changed
# mode) we treat as success.
_COINIT_APARTMENTTHREADED = 0x2
_S_OK = 0
_S_FALSE = 1
_RPC_E_CHANGED_MODE = 0x80010106


# --------------------------------------------------------------------------- #
# Pattern / property ids (from UIAutomationCore; mirror the vendored constants)
# --------------------------------------------------------------------------- #
_PAT_VALUE = 10002
_PAT_RANGEVALUE = 10003
_PAT_EXPANDCOLLAPSE = 10005
_PAT_SELECTIONITEM = 10010
_PAT_TOGGLE = 10015

_PROP_LEVEL = 30154
_PROP_POSITION_IN_SET = 30152
_PROP_SIZE_OF_SET = 30153
_PROP_FULL_DESCRIPTION = 30159

# Toggle / expand-collapse enum values.
_TOGGLE_OFF, _TOGGLE_ON, _TOGGLE_INDETERMINATE = 0, 1, 2
_EXPAND_COLLAPSED, _EXPAND_EXPANDED, _EXPAND_PARTIAL = 0, 1, 2


# --------------------------------------------------------------------------- #
# UIA ControlTypeId -> contracts ROLE_* key (complete mapping)
# --------------------------------------------------------------------------- #
# Port of ``UIAutomationProvider.MapControlTypeToRole`` re-expressed against the
# canonical Titan Access role vocabulary. Keyed by the raw UIA_*ControlTypeId so
# we never depend on the vendored library being importable.
_CONTROLTYPE_TO_ROLE = {
    50000: ROLE_BUTTON,        # UIA_ButtonControlTypeId
    50001: ROLE_IMAGE,         # UIA_CalendarControlTypeId
    50002: ROLE_CHECKBOX,      # UIA_CheckBoxControlTypeId
    50003: ROLE_COMBOBOX,      # UIA_ComboBoxControlTypeId
    50004: ROLE_EDIT,          # UIA_EditControlTypeId (-> password if protected)
    50005: ROLE_LINK,          # UIA_HyperlinkControlTypeId
    50006: ROLE_IMAGE,         # UIA_ImageControlTypeId
    50007: ROLE_LISTITEM,      # UIA_ListItemControlTypeId
    50008: ROLE_LISTBOX,       # UIA_ListControlTypeId
    50009: ROLE_MENU,          # UIA_MenuControlTypeId
    50010: ROLE_MENUBAR,       # UIA_MenuBarControlTypeId
    50011: ROLE_MENUITEM,      # UIA_MenuItemControlTypeId
    50012: ROLE_PROGRESSBAR,   # UIA_ProgressBarControlTypeId
    50013: ROLE_RADIO,         # UIA_RadioButtonControlTypeId
    50014: ROLE_SCROLLBAR,     # UIA_ScrollBarControlTypeId
    50015: ROLE_SLIDER,        # UIA_SliderControlTypeId
    50016: ROLE_SPINNER,       # UIA_SpinnerControlTypeId
    50017: ROLE_STATUSBAR,     # UIA_StatusBarControlTypeId
    50018: ROLE_TABCONTROL,    # UIA_TabControlTypeId
    50019: ROLE_TAB,           # UIA_TabItemControlTypeId
    50020: ROLE_TEXT,          # UIA_TextControlTypeId
    50021: ROLE_TOOLBAR,       # UIA_ToolBarControlTypeId
    50022: ROLE_TEXT,          # UIA_ToolTipControlTypeId
    50023: ROLE_TREE,          # UIA_TreeControlTypeId
    50024: ROLE_TREEITEM,      # UIA_TreeItemControlTypeId
    50025: ROLE_PANE,          # UIA_CustomControlTypeId
    50026: ROLE_GROUP,         # UIA_GroupControlTypeId
    50027: ROLE_UNKNOWN,       # UIA_ThumbControlTypeId
    50028: ROLE_GRID,          # UIA_DataGridControlTypeId
    50029: ROLE_LISTITEM,      # UIA_DataItemControlTypeId
    50030: ROLE_DOCUMENT,      # UIA_DocumentControlTypeId
    50031: ROLE_SPLIT_BUTTON,  # UIA_SplitButtonControlTypeId
    50032: ROLE_WINDOW,        # UIA_WindowControlTypeId
    50033: ROLE_PANE,          # UIA_PaneControlTypeId
    50034: ROLE_HEADING,       # UIA_HeaderControlTypeId
    50035: ROLE_HEADING,       # UIA_HeaderItemControlTypeId
    50036: ROLE_TABLE,         # UIA_TableControlTypeId
    50037: ROLE_UNKNOWN,       # UIA_TitleBarControlTypeId
    50038: ROLE_SEPARATOR,     # UIA_SeparatorControlTypeId
    50039: ROLE_PANE,          # UIA_SemanticZoomControlTypeId
    50040: ROLE_TOOLBAR,       # UIA_AppBarControlTypeId
}

# Control types that should expose a cell role when seen inside a grid/table.
# (Kept for completeness; data items default to list items as in the C# port.)
_GRID_CELL_TYPES = {50029}


def _role_for_control_type(control_type, is_password):
    role = _CONTROLTYPE_TO_ROLE.get(control_type, ROLE_PANE)
    if is_password and role == ROLE_EDIT:
        return ROLE_PASSWORD
    return role


# --------------------------------------------------------------------------- #
# Focus-changed COM event handler (raw comtypes)
# --------------------------------------------------------------------------- #
def _make_focus_handler_class():
    """Build the ``COMObject`` handler class bound to the generated interface.

    Done lazily so importing this module never touches COM. Returns ``None`` if
    the UIAutomationCore type library cannot be generated.
    """
    if not _COMTYPES_OK:
        return None
    try:
        uia_mod = comtypes.client.GetModule("UIAutomationCore.dll")
    except Exception as e:  # pragma: no cover
        print(f"[TitanAccess] UIAutomationCore module load failed: {e}")
        return None

    class _FocusChangedHandler(comtypes.COMObject):
        """Implements ``IUIAutomationFocusChangedEventHandler``.

        ``HandleFocusChangedEvent`` is invoked by UIA on an internal thread with
        the newly focused element. We keep it short: build the snapshot and fan
        it out. comtypes passes the COM ``this`` pointer as the first positional
        argument after ``self``.
        """

        _com_interfaces_ = [uia_mod.IUIAutomationFocusChangedEventHandler]

        def __init__(self, provider):
            super().__init__()
            self._provider = provider

        def IUIAutomationFocusChangedEventHandler_HandleFocusChangedEvent(
                self, this, sender):
            try:
                if sender is not None and self._provider is not None:
                    obj = self._provider.element_to_object(sender)
                    if obj is not None:
                        self._provider._dispatch(obj)
            except Exception as e:  # pragma: no cover - never raise into COM
                print(f"[TitanAccess] focus event error: {e}")
            return _S_OK

    return _FocusChangedHandler


# --------------------------------------------------------------------------- #
# Provider
# --------------------------------------------------------------------------- #
class UIAProvider:
    """UI Automation implementation of
    :class:`~titan_access.contracts.AccessibilityProviderLike`.

    Lifecycle: construct, :meth:`add_focus_listener`, :meth:`start`. On every OS
    focus change each listener receives a fresh :class:`AccessibleObject`. Call
    :meth:`stop` to unregister and release the COM objects.
    """

    def __init__(self):
        self._uia = None                       # IUIAutomation client
        self._handler = None                   # live COMObject (keep ref!)
        self._handler_cls = None
        self._listeners: List[FocusCallback] = []
        self._lock = threading.RLock()
        self._listening = False

        if not (_COMTYPES_OK and _UIA_LIB_OK):
            return

        # COM should already be initialised (apartment-threaded) on the caller's
        # thread, but guard defensively so a standalone caller still works.
        self._co_initialise()

        try:
            self._uia = self._create_client()
        except Exception as e:  # pragma: no cover
            print(f"[TitanAccess] UI Automation client creation failed: {e}")
            self._uia = None

    # -- COM bootstrap ----------------------------------------------------- #
    @staticmethod
    def _co_initialise():
        try:
            hr = ctypes.windll.ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
            # S_OK / S_FALSE both mean "usable on this thread".
            if hr not in (_S_OK, _S_FALSE) and (hr & 0xFFFFFFFF) != _RPC_E_CHANGED_MODE:
                print(f"[TitanAccess] CoInitializeEx returned 0x{hr & 0xFFFFFFFF:08X}")
        except Exception as e:  # pragma: no cover
            print(f"[TitanAccess] CoInitializeEx failed: {e}")

    @staticmethod
    def _create_client():
        """Create the IUIAutomation client (prefer CUIAutomation8, fall back)."""
        uia_mod = comtypes.client.GetModule("UIAutomationCore.dll")
        for clsid in (_CLSID_CUIAUTOMATION8, _CLSID_CUIAUTOMATION):
            try:
                return comtypes.client.CreateObject(
                    clsid, interface=uia_mod.IUIAutomation)
            except Exception:
                continue
        # Last resort: reuse whatever the vendored library already created.
        if _UIA_LIB_OK:
            try:
                from uiautomation.uiautomation import _AutomationClient
                return _AutomationClient.instance().IUIAutomation
            except Exception:
                pass
        raise RuntimeError("could not create an IUIAutomation client")

    # -- AccessibilityProviderLike ----------------------------------------- #
    def start(self) -> bool:
        """Register the focus-changed handler. Returns False if UIA is down."""
        if self._uia is None:
            return False
        with self._lock:
            if self._listening:
                return True
            try:
                self._handler_cls = self._handler_cls or _make_focus_handler_class()
                if self._handler_cls is None:
                    return False
                self._handler = self._handler_cls(self)
                # AddFocusChangedEventHandler(cacheRequest, handler). Passing a
                # cache request is the whole difference between a focus
                # announcement costing one delivery and costing thirty
                # cross-process property reads: the element arrives with
                # everything we are going to ask it already filled in.
                self._uia.AddFocusChangedEventHandler(
                    self._focus_cache_request(), self._handler)
                self._listening = True
                return True
            except Exception as e:
                print(f"[TitanAccess] AddFocusChangedEventHandler failed: {e}")
                self._handler = None
                return False

    def stop(self) -> None:
        """Unregister all handlers and drop the COM references."""
        with self._lock:
            if self._uia is not None and self._listening:
                try:
                    self._uia.RemoveAllEventHandlers()
                except Exception as e:  # pragma: no cover
                    print(f"[TitanAccess] RemoveAllEventHandlers failed: {e}")
            self._listening = False
            self._handler = None

    def add_focus_listener(self, callback: FocusCallback) -> None:
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def _dispatch(self, obj: AccessibleObject) -> None:
        """Fan a snapshot out to every listener (called on a COM thread)."""
        for cb in list(self._listeners):
            try:
                cb(obj)
            except Exception as e:  # pragma: no cover
                print(f"[TitanAccess] focus listener error: {e}")

    def get_focused_object(self) -> Optional[AccessibleObject]:
        if self._uia is None:
            return None
        try:
            element = self._uia.GetFocusedElement()
            return self.element_to_object(element) if element else None
        except Exception as e:
            print(f"[TitanAccess] GetFocusedElement failed: {e}")
            return None

    def object_from_point(self, x: int, y: int) -> Optional[AccessibleObject]:
        if not _UIA_LIB_OK:
            return None
        try:
            control = _auto.ControlFromPoint(x, y)
            return self._control_to_object(control) if control else None
        except Exception as e:
            print(f"[TitanAccess] object_from_point failed: {e}")
            return None

    def object_from_handle(self, hwnd: int) -> Optional[AccessibleObject]:
        if not _UIA_LIB_OK:
            return None
        try:
            control = _auto.ControlFromHandle(hwnd)
            return self._control_to_object(control) if control else None
        except Exception as e:
            print(f"[TitanAccess] object_from_handle failed: {e}")
            return None

    # -- cached reading ----------------------------------------------------- #
    @staticmethod
    def _focus_cache_request():
        """The cache request focus events are delivered with (None if no UIA)."""
        if _cache is None:
            return None
        try:
            return _cache.focus_request()
        except Exception:
            return None

    def _cached_element_to_object(self, element) -> Optional[AccessibleObject]:
        """Snapshot a focus element from its cache - no cross-process calls.

        Returns None when the element carries no cache and one cannot be filled
        in, so the caller falls back to the live property-by-property path.
        Every pattern value is gated on its ``Is<Pattern>PatternAvailable``
        property: UI Automation answers an unsupported property with its TYPE
        DEFAULT, so an element with no toggle pattern reports ToggleState 2 and
        would be announced "partially checked".
        """
        if _cache is None:
            return None
        cached = _cache.with_cache(element, self._focus_cache_request())
        if cached is None:
            return None
        c = _cache
        try:
            control_type = c.get(cached, c.CONTROL_TYPE, None)
            if control_type is None:
                return None
            native = c.control_for(cached, control_type)
            if native is None:
                return None
            obj = AccessibleObject(native=native, provider="uia")

            is_password = c.flag(cached, c.IS_PASSWORD, False)
            obj.role = _role_for_control_type(int(control_type), is_password)
            obj.name = c.text(cached, c.NAME)
            obj.help_text = c.text(cached, c.HELP_TEXT)
            obj.description = c.text(cached, c.FULL_DESCRIPTION)
            obj.value = self._cached_value(cached)
            obj.automation_id = c.text(cached, c.AUTOMATION_ID)
            obj.class_name = c.text(cached, c.CLASS_NAME)
            obj.framework_id = c.text(cached, c.FRAMEWORK_ID)
            obj.process_id = c.number(cached, c.PROCESS_ID)
            obj.hwnd = c.number(cached, c.NATIVE_WINDOW_HANDLE)
            obj.bounds = c.rect_of(cached) or (0, 0, 0, 0)
            obj.level = c.number(cached, c.LEVEL)
            obj.pos_in_set = c.number(cached, c.POSITION_IN_SET)
            obj.size_of_set = c.number(cached, c.SIZE_OF_SET)
            obj.states = self._cached_states(cached, is_password)
            if obj.role == ROLE_LINK:
                obj.parameter = obj.value
            return obj
        except Exception as e:
            if os.environ.get("TITAN_ACCESS_DEBUG"):
                print(f"[TitanAccess] cached snapshot failed: {e}")
            return None

    @staticmethod
    def _cached_value(cached) -> str:
        c = _cache
        value = c.pattern_value(cached, c.IS_VALUE_AVAILABLE, c.VALUE_VALUE, None)
        if value not in (None, ""):
            return str(value)
        value = c.pattern_value(cached, c.IS_RANGEVALUE_AVAILABLE,
                                c.RANGEVALUE_VALUE, None)
        if value is None:
            return ""
        # Trim a redundant ".0" so "30" reads better than "30.0".
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    @staticmethod
    def _cached_states(cached, is_password):
        c = _cache
        states = set()
        if not c.flag(cached, c.IS_ENABLED, True):
            states.add(STATE_UNAVAILABLE)
        if c.flag(cached, c.HAS_KEYBOARD_FOCUS, False):
            states.add(STATE_FOCUSED)
        if c.flag(cached, c.IS_OFFSCREEN, False):
            states.add(_STATE_OFFSCREEN)
        if c.flag(cached, c.IS_REQUIRED_FOR_FORM, False):
            states.add(STATE_REQUIRED)
        if is_password:
            states.add(STATE_PROTECTED)
        toggle = c.pattern_value(cached, c.IS_TOGGLE_AVAILABLE, c.TOGGLE_STATE, None)
        if toggle == c.TOGGLE_ON:
            states.add(STATE_CHECKED)
        elif toggle == c.TOGGLE_INDETERMINATE:
            states.add(STATE_PARTIAL)
        expand = c.pattern_value(cached, c.IS_EXPANDCOLLAPSE_AVAILABLE,
                                 c.EXPANDCOLLAPSE_STATE, None)
        if expand in (c.EXPAND_EXPANDED, c.EXPAND_PARTIAL):
            states.add(STATE_EXPANDED)
        elif expand == c.EXPAND_COLLAPSED:
            states.add(STATE_COLLAPSED)
        # EXPAND_LEAF means "nothing to expand" and is not a state to announce.
        if c.pattern_value(cached, c.IS_SELECTIONITEM_AVAILABLE,
                           c.SELECTIONITEM_IS_SELECTED, False):
            states.add(STATE_SELECTED)
        if c.pattern_value(cached, c.IS_VALUE_AVAILABLE, c.VALUE_IS_READONLY,
                           False):
            states.add(STATE_READONLY)
        return states

    # -- element -> snapshot ----------------------------------------------- #
    def element_to_object(self, element) -> Optional[AccessibleObject]:
        """Build an :class:`AccessibleObject` from a UIA element.

        Accepts either a raw ``IUIAutomationElement`` (from the focus event /
        ``GetFocusedElement``) or an already-wrapped vendored ``Control`` (e.g.
        the sibling/parent Controls produced by object navigation). The raw
        pointer is wrapped with the ``Control`` helper so we can reuse its
        property accessors and pattern getters.
        """
        if element is None or not _UIA_LIB_OK:
            return None
        # Already a uiautomation.Control? Use it directly (it exposes .Element).
        if hasattr(element, "Element") and hasattr(element, "GetParentControl"):
            return self._control_to_object(element)
        # Raw element: read it out of its cache in one go. This is the normal
        # path (every focus event lands here) and the reason focus is announced
        # promptly in UWP / Chromium windows instead of after ~30 RPCs.
        obj = self._cached_element_to_object(element)
        if obj is not None:
            return obj
        try:
            control = _auto.Control.CreateControlFromElement(element)
        except Exception as e:  # pragma: no cover
            print(f"[TitanAccess] CreateControlFromElement failed: {e}")
            control = None
        if control is None:
            return None
        return self._control_to_object(control)

    def _control_to_object(self, control, native=None) -> Optional[AccessibleObject]:
        """Flatten a vendored ``Control`` into a provider-agnostic snapshot."""
        if control is None:
            return None
        try:
            element = control.Element
        except Exception:
            element = native

        # ``native`` must be the vendored ``uiautomation.Control``: object_nav
        # (GetNextSiblingControl, ...) and editable_text (GetTextPattern) call
        # Control methods on it. The raw UIA element stays reachable through
        # ``control.Element`` for anything that needs it.
        obj = AccessibleObject(native=control, provider="uia")

        # -- identity / text ----------------------------------------------- #
        obj.name = _safe(lambda: control.Name, "")
        is_password = bool(_safe(lambda: control.IsPassword, False))
        control_type = _safe(lambda: control.ControlType, 0)
        obj.role = _role_for_control_type(control_type, is_password)
        obj.help_text = _safe(lambda: control.HelpText, "")
        obj.description = _safe(
            lambda: control.GetPropertyValue(_PROP_FULL_DESCRIPTION), "") or ""

        # -- value (ValuePattern, then RangeValuePattern) ------------------ #
        obj.value = self._read_value(control)

        # -- identity fields ----------------------------------------------- #
        obj.automation_id = _safe(lambda: control.AutomationId, "")
        obj.class_name = _safe(lambda: control.ClassName, "")
        obj.framework_id = _safe(lambda: control.FrameworkId, "")
        obj.process_id = int(_safe(lambda: control.ProcessId, 0) or 0)
        obj.hwnd = int(_safe(lambda: control.NativeWindowHandle, 0) or 0)

        # -- geometry ------------------------------------------------------- #
        obj.bounds = self._read_bounds(control)

        # -- hierarchy / collection context -------------------------------- #
        obj.level = _positive(_safe(
            lambda: control.GetPropertyValue(_PROP_LEVEL), 0))
        obj.pos_in_set = _positive(_safe(
            lambda: control.GetPropertyValue(_PROP_POSITION_IN_SET), 0))
        obj.size_of_set = _positive(_safe(
            lambda: control.GetPropertyValue(_PROP_SIZE_OF_SET), 0))

        # -- states --------------------------------------------------------- #
        obj.states = self._read_states(control, is_password)

        # -- parameter (e.g. link URL) ------------------------------------- #
        if obj.role == ROLE_LINK and not obj.value:
            obj.parameter = self._read_value(control)
        elif obj.value and obj.role == ROLE_LINK:
            obj.parameter = obj.value

        return obj

    # -- field readers ----------------------------------------------------- #
    @staticmethod
    def _read_value(control) -> str:
        # ValuePattern first (edit fields, combos, links).
        pat = _safe(lambda: control.GetPattern(_PAT_VALUE), None)
        if pat is not None:
            val = _safe(lambda: pat.Value, None)
            if val:
                return str(val)
        # RangeValuePattern (sliders, spinners, progress bars).
        rng = _safe(lambda: control.GetPattern(_PAT_RANGEVALUE), None)
        if rng is not None:
            val = _safe(lambda: rng.Value, None)
            if val is not None:
                # Trim a redundant ".0" so "30" reads better than "30.0".
                if isinstance(val, float) and val.is_integer():
                    return str(int(val))
                return str(val)
        return ""

    @staticmethod
    def _read_bounds(control):
        try:
            rect = control.BoundingRectangle
            left = int(getattr(rect, "left", 0))
            top = int(getattr(rect, "top", 0))
            right = int(getattr(rect, "right", 0))
            bottom = int(getattr(rect, "bottom", 0))
            return (left, top, right, bottom)
        except Exception:
            return (0, 0, 0, 0)

    @staticmethod
    def _read_states(control, is_password):
        states = set()

        if not _safe(lambda: control.IsEnabled, True):
            states.add(STATE_UNAVAILABLE)
        if _safe(lambda: control.HasKeyboardFocus, False):
            states.add(STATE_FOCUSED)
        if _safe(lambda: control.IsOffscreen, False):
            states.add(_STATE_OFFSCREEN)
        if _safe(lambda: control.IsRequiredForForm, False):
            states.add(STATE_REQUIRED)
        if is_password:
            states.add(STATE_PROTECTED)

        # Toggle (check boxes, toggle buttons).
        toggle = _safe(lambda: control.GetPattern(_PAT_TOGGLE), None)
        if toggle is not None:
            ts = _safe(lambda: toggle.ToggleState, None)
            if ts == _TOGGLE_ON:
                states.add(STATE_CHECKED)
            elif ts == _TOGGLE_INDETERMINATE:
                states.add(STATE_PARTIAL)

        # Expand / collapse (tree items, combo boxes, menus).
        expand = _safe(lambda: control.GetPattern(_PAT_EXPANDCOLLAPSE), None)
        if expand is not None:
            es = _safe(lambda: expand.ExpandCollapseState, None)
            if es == _EXPAND_EXPANDED or es == _EXPAND_PARTIAL:
                states.add(STATE_EXPANDED)
            elif es == _EXPAND_COLLAPSED:
                states.add(STATE_COLLAPSED)

        # Selection (list items, tabs, tree items).
        sel = _safe(lambda: control.GetPattern(_PAT_SELECTIONITEM), None)
        if sel is not None and _safe(lambda: sel.IsSelected, False):
            states.add(STATE_SELECTED)

        # Read-only (edit fields via ValuePattern).
        value_pat = _safe(lambda: control.GetPattern(_PAT_VALUE), None)
        if value_pat is not None and _safe(lambda: value_pat.IsReadOnly, False):
            states.add(STATE_READONLY)

        return states


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _safe(getter, default):
    """Call a property/pattern getter, swallowing COM errors."""
    try:
        result = getter()
        return default if result is None else result
    except Exception:
        return default


def _positive(value):
    """Coerce a UIA collection index to a non-negative int (0 = unknown)."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return 0
    return v if v > 0 else 0


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def get_provider() -> UIAProvider:
    """Return a fresh :class:`UIAProvider` instance."""
    return UIAProvider()
