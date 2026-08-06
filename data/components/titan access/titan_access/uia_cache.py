# -*- coding: utf-8 -*-
"""Bulk UI Automation reads, the way a screen reader has to do them.

Every property of a UIA element lives in ANOTHER process. Reading ``Name`` is a
cross-process RPC; reading name, role, rectangle, state, level and value is six
of them. Titan Access used to read a focused control that way (about thirty
round trips per focus change) and to build a browse-mode buffer that way (about
ten per element, thousands of elements per page). That is the whole of the
"it lags on web pages and in UWP apps" problem: not the logic, the number of
calls.

UI Automation has the answer built in, and it is what NVDA and JAWS use: a
**cache request**. You say once which properties you want, and then

* ``IUIAutomationElement.FindAllBuildCache`` returns an entire subtree WITH
  those properties already filled in - one round trip for the whole page, and
* ``AddFocusChangedEventHandler(cacheRequest, ...)`` delivers focus events whose
  element already carries them - zero round trips for a focus announcement.

Reading a cached property afterwards is an in-process memory read. Measured on
this machine (Chromium content, 192 elements): a walk reading six properties per
element took 2088 ms, the cached build took 448 ms and reading FOURTEEN
properties of every element out of the cache took 7 ms. Per focused element:
9.6 ms live against 1.4 ms cached.

Two traps this module exists to hide:

* A property the element does not support comes back as its **type default**,
  not as nothing - an element with no toggle pattern reports ToggleState 2
  ("partially checked"). So every pattern property is gated on its
  ``Is<Pattern>PatternAvailable`` property, which is itself cached.
* ``GetCachedPropertyValue(BoundingRectangle)`` answers ``[left, top, width,
  height]`` while ``CachedBoundingRectangle`` answers a RECT. Use
  :func:`rect_of`.

Nothing here raises: if UIA or comtypes is missing, :func:`client` returns None
and every caller falls back to the live path it already had.
"""

from __future__ import annotations

import os
import sys
import threading

_DBG = bool(os.environ.get("TITAN_ACCESS_DEBUG"))

# The vendored uiautomation package (its lib dir is normally already on the path
# via uia_focus, but this module must be importable on its own).
_LIB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)


# --------------------------------------------------------------------------- #
# Property ids (UIAutomationCore). Named so the call sites read as English.
# --------------------------------------------------------------------------- #
BOUNDING_RECTANGLE = 30001
PROCESS_ID = 30002
CONTROL_TYPE = 30003
LOCALIZED_CONTROL_TYPE = 30004
NAME = 30005
HAS_KEYBOARD_FOCUS = 30008
IS_KEYBOARD_FOCUSABLE = 30009
IS_ENABLED = 30010
AUTOMATION_ID = 30011
CLASS_NAME = 30012
HELP_TEXT = 30013
IS_PASSWORD = 30019
NATIVE_WINDOW_HANDLE = 30020
IS_OFFSCREEN = 30022
FRAMEWORK_ID = 30024
IS_REQUIRED_FOR_FORM = 30025
ARIA_ROLE = 30101
POSITION_IN_SET = 30152
SIZE_OF_SET = 30153
LEVEL = 30154
FULL_DESCRIPTION = 30159

# "Does this element support that pattern?" - the gate every pattern value needs.
IS_EXPANDCOLLAPSE_AVAILABLE = 30028
IS_RANGEVALUE_AVAILABLE = 30033
IS_SELECTIONITEM_AVAILABLE = 30036
IS_TOGGLE_AVAILABLE = 30041
IS_VALUE_AVAILABLE = 30043

# Pattern property values.
VALUE_VALUE = 30045
VALUE_IS_READONLY = 30046
RANGEVALUE_VALUE = 30047
EXPANDCOLLAPSE_STATE = 30070
SELECTIONITEM_IS_SELECTED = 30079
TOGGLE_STATE = 30086

# Enum values worth naming.
TOGGLE_OFF, TOGGLE_ON, TOGGLE_INDETERMINATE = 0, 1, 2
EXPAND_COLLAPSED, EXPAND_EXPANDED, EXPAND_PARTIAL, EXPAND_LEAF = 0, 1, 2, 3

# TreeScope.
SCOPE_ELEMENT = 1
SCOPE_CHILDREN = 2
SCOPE_DESCENDANTS = 4
SCOPE_SUBTREE = 7

# AutomationElementMode. FULL keeps the returned elements usable for patterns,
# SetFocus and later live reads - which a screen reader needs, because pressing
# Enter on a buffer entry must reach the real control. NONE would be faster and
# useless.
MODE_NONE, MODE_FULL = 0, 1

# What a focus announcement needs: everything accessible.describe() and the
# context presenter can ask for, so a focus change costs exactly one delivery.
FOCUS_PROPERTIES = (
    NAME, CONTROL_TYPE, LOCALIZED_CONTROL_TYPE, AUTOMATION_ID, CLASS_NAME,
    FRAMEWORK_ID, PROCESS_ID, NATIVE_WINDOW_HANDLE, BOUNDING_RECTANGLE,
    HELP_TEXT, FULL_DESCRIPTION, LEVEL, POSITION_IN_SET, SIZE_OF_SET,
    IS_ENABLED, HAS_KEYBOARD_FOCUS, IS_OFFSCREEN, IS_PASSWORD,
    IS_REQUIRED_FOR_FORM, ARIA_ROLE,
    IS_VALUE_AVAILABLE, VALUE_VALUE, VALUE_IS_READONLY,
    IS_RANGEVALUE_AVAILABLE, RANGEVALUE_VALUE,
    IS_TOGGLE_AVAILABLE, TOGGLE_STATE,
    IS_SELECTIONITEM_AVAILABLE, SELECTIONITEM_IS_SELECTED,
    IS_EXPANDCOLLAPSE_AVAILABLE, EXPANDCOLLAPSE_STATE,
)

# What a virtual document needs. Deliberately smaller than the focus set: this
# one is paid per element of a whole page, and the cost of a cached build grows
# with the number of properties asked for.
BUFFER_PROPERTIES = (
    NAME, CONTROL_TYPE, LOCALIZED_CONTROL_TYPE, AUTOMATION_ID,
    BOUNDING_RECTANGLE, ARIA_ROLE, LEVEL, POSITION_IN_SET, SIZE_OF_SET,
    IS_ENABLED, IS_OFFSCREEN,
    IS_VALUE_AVAILABLE, VALUE_VALUE,
    IS_RANGEVALUE_AVAILABLE, RANGEVALUE_VALUE,
    IS_TOGGLE_AVAILABLE, TOGGLE_STATE,
    IS_SELECTIONITEM_AVAILABLE, SELECTIONITEM_IS_SELECTED,
)


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #
_lock = threading.Lock()
_client = None
_client_tried = False


def client():
    """The process-wide ``IUIAutomation`` (None when UIA is unavailable)."""
    global _client, _client_tried
    with _lock:
        if _client is not None or _client_tried:
            return _client
        _client_tried = True
        try:
            from uiautomation.uiautomation import _AutomationClient
            _client = _AutomationClient.instance().IUIAutomation
        except Exception as e:
            print(f"[TitanAccess] uia_cache: no UI Automation client: {e}")
            _client = None
        return _client


def available() -> bool:
    return client() is not None


def make_request(properties, mode=MODE_FULL, tree_filter="control"):
    """A cache request for *properties* (None when UIA is unavailable).

    ``tree_filter`` picks the view the cached tree is expressed in: ``control``
    is what a screen reader wants (layout-only elements dropped), ``raw`` keeps
    everything, ``content`` is the narrowest.
    """
    iuia = client()
    if iuia is None:
        return None
    try:
        request = iuia.CreateCacheRequest()
        for pid in properties:
            request.AddProperty(pid)
        request.AutomationElementMode = mode
        condition = view_condition(tree_filter)
        if condition is not None:
            request.TreeFilter = condition
        return request
    except Exception as e:
        print(f"[TitanAccess] uia_cache: cache request failed: {e}")
        return None


def view_condition(which="control"):
    """``ControlViewCondition`` / ``RawViewCondition`` / ``ContentViewCondition``."""
    iuia = client()
    if iuia is None:
        return None
    try:
        return {
            "control": iuia.ControlViewCondition,
            "raw": iuia.RawViewCondition,
            "content": iuia.ContentViewCondition,
        }.get(which, iuia.ControlViewCondition)
    except Exception:
        return None


# Built once and reused: creating a cache request is cheap but not free, and
# these two are asked for on the focus path.
_focus_request = None
_buffer_request = None


def focus_request():
    global _focus_request
    if _focus_request is None:
        _focus_request = make_request(FOCUS_PROPERTIES)
    return _focus_request


def buffer_request():
    global _buffer_request
    if _buffer_request is None:
        _buffer_request = make_request(BUFFER_PROPERTIES)
    return _buffer_request


# --------------------------------------------------------------------------- #
# Reading a cached element
# --------------------------------------------------------------------------- #
def has_cache(element, probe=CONTROL_TYPE) -> bool:
    """True when *element* carries a cache that includes *probe*.

    The probe matters: an element can arrive already cached under a DIFFERENT
    request (the buffer's, say), and reading a focus snapshot out of that cache
    would silently miss every property the other request never asked for. So
    the caller names a property only its own request carries.
    """
    if element is None:
        return False
    try:
        element.GetCachedPropertyValue(probe)
        return True
    except Exception:
        return False


def with_cache(element, request=None, probe=HAS_KEYBOARD_FOCUS):
    """*element* with the focus cache filled in, or None if impossible.

    An element delivered by a cached focus event already has one and is returned
    untouched; anything else costs a single round trip
    (``BuildUpdatedCache``) - still one instead of thirty.
    """
    if element is None:
        return None
    if has_cache(element, probe):
        return element
    request = request or focus_request()
    if request is None:
        return None
    try:
        return element.BuildUpdatedCache(request)
    except Exception as e:
        if _DBG:
            print(f"[TitanAccess] uia_cache: BuildUpdatedCache failed: {e}")
        return None


def get(element, pid, default=None):
    """One cached property, or *default*.

    Only scalars are trusted: an unsupported property answers with UIA's
    reserved "not supported" object, which is a COM pointer and would otherwise
    sail through as a truthy value.
    """
    try:
        value = element.GetCachedPropertyValue(pid)
    except Exception:
        return default
    if value is None:
        return default
    if isinstance(value, (str, int, float, bool)):
        return value
    return default


def text(element, pid) -> str:
    value = get(element, pid, "")
    return value.strip() if isinstance(value, str) else ""


def flag(element, pid, default=False) -> bool:
    value = get(element, pid, None)
    return default if value is None else bool(value)


def number(element, pid, default=0) -> int:
    """A cached property as a non-negative int (0 = unknown/absent)."""
    value = get(element, pid, None)
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default


def rect_of(element) -> tuple:
    """``(left, top, right, bottom)`` in screen pixels, or ``()``.

    Uses the typed ``CachedBoundingRectangle`` accessor: the same property read
    through ``GetCachedPropertyValue`` answers width/height instead of
    right/bottom, which is a bug that only shows up as controls being clicked in
    the wrong place.
    """
    try:
        r = element.CachedBoundingRectangle
        return (int(r.left), int(r.top), int(r.right), int(r.bottom))
    except Exception:
        return ()


def pattern_value(element, available_pid, value_pid, default=None):
    """A pattern's cached property, but only when the pattern really exists."""
    if not flag(element, available_pid, False):
        return default
    return get(element, value_pid, default)


def find_all_cached(root_element, request=None, scope=SCOPE_DESCENDANTS,
                    view="control"):
    """Every element under *root_element*, with its properties already cached.

    One cross-process call for the whole subtree. Returns a plain list in tree
    order (empty on any failure, so the caller falls back to walking).
    """
    if root_element is None:
        return []
    request = request or buffer_request()
    condition = view_condition(view)
    if request is None or condition is None:
        return []
    try:
        array = root_element.FindAllBuildCache(scope, condition, request)
    except Exception as e:
        if _DBG:
            print(f"[TitanAccess] uia_cache: FindAllBuildCache failed: {e}")
        return []
    try:
        return [array.GetElement(i) for i in range(int(array.Length))]
    except Exception as e:
        if _DBG:
            print(f"[TitanAccess] uia_cache: element array read failed: {e}")
        return []


def raw_element(control):
    """The ``IUIAutomationElement`` behind a vendored ``Control`` (or itself)."""
    if control is None:
        return None
    element = getattr(control, "Element", None)
    return element if element is not None else control


def control_for(element, control_type=None):
    """Wrap a raw element in the vendored ``Control`` subclass for its type.

    ``Control.CreateControlFromElement`` reads ``CurrentControlType`` to pick the
    class, which is a cross-process call we already have the answer to.
    """
    if element is None:
        return None
    try:
        import uiautomation as auto
    except Exception:
        return None
    if control_type is None:
        control_type = get(element, CONTROL_TYPE, None)
    try:
        if control_type is not None:
            ctor = auto.ControlConstructors.get(int(control_type))
            if ctor is not None:
                return ctor(element=element)
        return auto.Control.CreateControlFromElement(element)
    except Exception:
        return None
