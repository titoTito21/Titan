# -*- coding: utf-8 -*-
"""A flat virtual document over ANY window.

Browse mode turned a *web page* into a flat list of elements that arrow keys and
single-letter quick navigation walk. Nothing about that idea is web-specific:
what a screen reader needs in a program that cannot be tabbed through - an old
Win32 dialog, a custom-drawn installer, a game menu - is exactly the same flat
document. This module is that document, built from whatever the window is
willing to tell us, in descending order of trust:

    1. ``uia``   UI Automation: modern apps, the richest source.
    2. ``msaa``  IAccessible / oleacc: legacy Win32, VB6, Delphi, MFC. Windows
                 proxies the standard controls, so a program written in 1998
                 that never heard of accessibility still reports its buttons,
                 its list items and their state.
    3. ``win32`` The raw child-window tree: class name -> role, window text ->
                 name. The last resort that needs no accessibility at all - it
                 works on a program that answers neither of the above, and it is
                 also what supplies the labels (a Static next to a nameless
                 Edit) those programs never associate.
    4. ``ocr``   The picture, read by the AI (see :mod:`titan_access.ocr_assist`).
                 Only when everything above came back empty, only when Titan's
                 AI features are on, and only with the user's consent - it sends
                 a picture of their screen to their provider.

:func:`build_for_window` walks those tiers and returns the first that produced a
usable document, so the caller never has to know which one answered. Every node
carries what it needs to be acted on (:func:`activate`, :func:`focus_node`), so
pressing Enter on an entry presses the real control whichever tier produced it.

Nothing here touches the keyboard hook thread: building is bounded (depth, node
count, wall clock) and the caller runs it on the engine's background reader.

This module emits no user-facing text of its own.
"""

import ctypes
import os
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from titan_access import contracts as C

_DBG = bool(os.environ.get("TITAN_ACCESS_DEBUG"))
_IS_WINDOWS = os.name == "nt"

# Bounds: a virtual document must never stall the reader, however big the app.
MAX_DEPTH = 30
MAX_NODES = 4000
BUILD_BUDGET_S = 6.0

# How many nodes a tier must produce before we accept its answer and stop
# trying cheaper ones. One node is what an empty container looks like.
MIN_USEFUL_NODES = 2

# UIA control types that are pure grouping / layout wrappers: their children are
# the content, they themselves are noise to arrow through (NVDA presents the
# buffer flat). Their descendants are still walked.
_WRAPPER_TYPES = {
    "GroupControl", "PaneControl", "DocumentControl", "WindowControl",
    "TitleBarControl", "ThumbControl", "CustomControl",
}

# UIA ControlTypeName -> Titan role key.
_UIA_TYPE_TO_ROLE = {
    "ButtonControl": C.ROLE_BUTTON,
    "SplitButtonControl": C.ROLE_SPLIT_BUTTON,
    "HyperlinkControl": C.ROLE_LINK,
    "EditControl": C.ROLE_EDIT,
    "DocumentControl": C.ROLE_DOCUMENT,
    "CheckBoxControl": C.ROLE_CHECKBOX,
    "RadioButtonControl": C.ROLE_RADIO,
    "ComboBoxControl": C.ROLE_COMBOBOX,
    "ListControl": C.ROLE_LISTBOX,
    "ListItemControl": C.ROLE_LISTITEM,
    "TreeControl": C.ROLE_TREE,
    "TreeItemControl": C.ROLE_TREEITEM,
    "MenuControl": C.ROLE_MENU,
    "MenuBarControl": C.ROLE_MENUBAR,
    "MenuItemControl": C.ROLE_MENUITEM,
    "TabControl": C.ROLE_TABCONTROL,
    "TabItemControl": C.ROLE_TAB,
    "SliderControl": C.ROLE_SLIDER,
    "SpinnerControl": C.ROLE_SPINNER,
    "ProgressBarControl": C.ROLE_PROGRESSBAR,
    "ScrollBarControl": C.ROLE_SCROLLBAR,
    "TextControl": C.ROLE_TEXT,
    "ImageControl": C.ROLE_IMAGE,
    "TableControl": C.ROLE_TABLE,
    "DataGridControl": C.ROLE_GRID,
    "DataItemControl": C.ROLE_GRIDITEM,
    "HeaderItemControl": C.ROLE_HEADING,
    "ToolBarControl": C.ROLE_TOOLBAR,
    "StatusBarControl": C.ROLE_STATUSBAR,
    "GroupControl": C.ROLE_GROUP,
    "SeparatorControl": C.ROLE_SEPARATOR,
    "PaneControl": C.ROLE_PANE,
    "WindowControl": C.ROLE_WINDOW,
    "CalendarControl": C.ROLE_TABLE,
    "HeaderControl": C.ROLE_TABLE,
}

# Window class (lower-case) -> Titan role key, for the raw child-window tier.
# These are the classes Windows itself provides plus the ones every old toolkit
# reuses; anything unknown becomes a pane and is kept only if it has text.
_CLASS_TO_ROLE = {
    "edit": C.ROLE_EDIT,
    "richedit": C.ROLE_EDIT,
    "richedit20a": C.ROLE_EDIT,
    "richedit20w": C.ROLE_EDIT,
    "richedit50w": C.ROLE_EDIT,
    "static": C.ROLE_TEXT,
    "listbox": C.ROLE_LISTBOX,
    "combobox": C.ROLE_COMBOBOX,
    "comboboxex32": C.ROLE_COMBOBOX,
    "syslistview32": C.ROLE_LISTBOX,
    "systreeview32": C.ROLE_TREE,
    "systabcontrol32": C.ROLE_TABCONTROL,
    "msctls_progress32": C.ROLE_PROGRESSBAR,
    "msctls_trackbar32": C.ROLE_SLIDER,
    "msctls_updown32": C.ROLE_SPINNER,
    "msctls_statusbar32": C.ROLE_STATUSBAR,
    "scrollbar": C.ROLE_SCROLLBAR,
    "toolbarwindow32": C.ROLE_TOOLBAR,
    "sysheader32": C.ROLE_TABLE,
    "syslink": C.ROLE_LINK,
    "sysdatetimepick32": C.ROLE_EDIT,
    "sysmonthcal32": C.ROLE_TABLE,
    "msctls_hotkey32": C.ROLE_EDIT,
}

# UIA property ids used for language-independent web semantics.
_UIA_PROP_ARIAROLE = 30101
_UIA_PROP_LEVEL = 30154

# ARIA role -> Titan role key. Only the roles whose ARIA name says something the
# control type does not; everything else keeps its control type's role.
_ARIA_TO_ROLE = {
    "heading": C.ROLE_HEADING,
    "link": C.ROLE_LINK,
    "button": C.ROLE_BUTTON,
    "checkbox": C.ROLE_CHECKBOX,
    "radio": C.ROLE_RADIO,
    "textbox": C.ROLE_EDIT,
    "searchbox": C.ROLE_EDIT,
    "combobox": C.ROLE_COMBOBOX,
    "listbox": C.ROLE_LISTBOX,
    "option": C.ROLE_LISTITEM,
    "listitem": C.ROLE_LISTITEM,
    "menuitem": C.ROLE_MENUITEM,
    "tab": C.ROLE_TAB,
    "img": C.ROLE_IMAGE,
    "image": C.ROLE_IMAGE,
    "table": C.ROLE_TABLE,
    "grid": C.ROLE_GRID,
    "cell": C.ROLE_CELL,
    "gridcell": C.ROLE_CELL,
    "separator": C.ROLE_SEPARATOR,
    "slider": C.ROLE_SLIDER,
    "progressbar": C.ROLE_PROGRESSBAR,
    "article": C.ROLE_TEXT,
    "paragraph": C.ROLE_TEXT,
    # Landmarks: a group is what quick navigation looks for (key D / N).
    "navigation": C.ROLE_GROUP,
    "main": C.ROLE_GROUP,
    "banner": C.ROLE_GROUP,
    "contentinfo": C.ROLE_GROUP,
    "complementary": C.ROLE_GROUP,
    "region": C.ROLE_GROUP,
    "search": C.ROLE_GROUP,
    "form": C.ROLE_GROUP,
}

# Classes never worth a buffer entry.
_CLASS_SKIP = {"tooltips_class32", "msctls_hotkey32", "shell embedding",
               "#32770lite"}

# Roles that are worth stopping on even with no name (they can be acted on and
# the announcer says what they are).
_ALWAYS_KEEP_ROLES = {
    C.ROLE_BUTTON, C.ROLE_SPLIT_BUTTON, C.ROLE_EDIT, C.ROLE_PASSWORD,
    C.ROLE_CHECKBOX, C.ROLE_RADIO, C.ROLE_COMBOBOX, C.ROLE_LISTITEM,
    C.ROLE_TREEITEM, C.ROLE_MENUITEM, C.ROLE_TAB, C.ROLE_SLIDER,
    C.ROLE_SPINNER, C.ROLE_LINK, C.ROLE_CELL, C.ROLE_GRIDITEM,
}


# =========================================================================== #
# Node
# =========================================================================== #
@dataclass
class VNode:
    """One entry of a virtual document, whatever built it."""

    name: str = ""
    role: str = C.ROLE_UNKNOWN
    value: str = ""
    level: int = 0                      # heading / tree level (0 = unknown)
    states: tuple = ()
    rect: tuple = ()                    # (left, top, right, bottom) screen px
    source: str = ""                    # uia | msaa | win32 | ocr | ia2
    element: Any = None                 # live uiautomation Control (uia)
    acc: Any = None                     # IAccessible (msaa)
    child_id: int = 0                   # MSAA child id
    hwnd: int = 0                       # owning window (msaa / win32)
    ocr_ref: Any = None                 # src.ai.ocr Element (ocr)
    pos_in_set: int = 0
    size_of_set: int = 0

    @property
    def text(self) -> str:
        """What arrow navigation reads out for this node."""
        if self.name and self.value and self.value != self.name:
            return f"{self.name} {self.value}"
        return self.name or self.value

    @property
    def is_heading(self) -> bool:
        return self.role == C.ROLE_HEADING or self.level > 0

    @property
    def centre(self):
        if not self.rect or len(self.rect) != 4:
            return None
        left, top, right, bottom = self.rect
        if right <= left or bottom <= top:
            return None
        return ((left + right) // 2, (top + bottom) // 2)


@dataclass
class VirtualDocument:
    """A built buffer plus what it was built from (so it can be re-checked)."""

    nodes: List[VNode] = field(default_factory=list)
    source: str = ""
    hwnd: int = 0
    title: str = ""
    signature: tuple = ()               # cheap "is this still the same screen?"
    built_at: float = field(default_factory=time.time)

    def __len__(self):
        return len(self.nodes)

    def __bool__(self):
        return bool(self.nodes)


# =========================================================================== #
# Win32 helpers (defensive; never raise)
# =========================================================================== #
if _IS_WINDOWS:
    _user32 = ctypes.windll.user32
else:                                    # pragma: no cover - not our platform
    _user32 = None

_ENUM_PROC = (ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
              if _IS_WINDOWS else None)


def window_text(hwnd) -> str:
    """``GetWindowText`` (never raises, always a str)."""
    if not _IS_WINDOWS or not hwnd:
        return ""
    try:
        n = _user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        return (buf.value or "").strip()
    except Exception:
        return ""


def window_class(hwnd) -> str:
    if not _IS_WINDOWS or not hwnd:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, buf, 256)
        return (buf.value or "").strip().lower()
    except Exception:
        return ""


def window_rect(hwnd) -> tuple:
    if not _IS_WINDOWS or not hwnd:
        return ()
    try:
        rect = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return ()
        return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except Exception:
        return ()


def foreground_hwnd() -> int:
    if not _IS_WINDOWS:
        return 0
    try:
        return int(_user32.GetForegroundWindow())
    except Exception:
        return 0


def _is_visible(hwnd) -> bool:
    try:
        return bool(_user32.IsWindowVisible(hwnd))
    except Exception:
        return False


def _child_windows(hwnd, limit=MAX_NODES):
    """Every descendant window of *hwnd*, in z-order, bounded."""
    found = []
    if not _IS_WINDOWS or not hwnd:
        return found

    def _walk(parent, depth):
        if depth > 8 or len(found) >= limit:
            return
        kids = []

        def _cb(child, _lparam):
            kids.append(int(child))
            return True

        try:
            _user32.EnumChildWindows(parent, _ENUM_PROC(_cb), 0)
        except Exception:
            return
        for child in kids:
            if len(found) >= limit:
                return
            found.append(child)

    # EnumChildWindows already recurses into grandchildren, so one call is the
    # whole tree in z-order -- which is close enough to reading order for a
    # dialog laid out the usual way.
    _walk(hwnd, 0)
    return found


# =========================================================================== #
# Tier 1: UI Automation
# =========================================================================== #
def build_uia(root, deadline=None) -> List[VNode]:
    """Flatten the UIA subtree under *root* (a ``uiautomation`` Control)."""
    try:
        import uiautomation as auto
    except Exception:
        return []
    if root is None:
        return []
    from titan_access import presentation as pres

    nodes: List[VNode] = []
    try:
        walker = auto.WalkControl(root, includeTop=False, maxDepth=MAX_DEPTH)
    except Exception:
        return nodes
    for control, _depth in walker:
        if deadline and time.time() > deadline:
            break
        try:
            if pres.presentation_type(control) == pres.UNAVAILABLE:
                continue
            ctype = control.ControlTypeName or ""
            name = (control.Name or "").strip()
        except Exception:
            continue
        if ctype in _WRAPPER_TYPES and not _wrapper_worth_keeping(ctype, name):
            continue
        role = _UIA_TYPE_TO_ROLE.get(ctype, C.ROLE_UNKNOWN)
        # Web content states its real role in ARIA, not in the control type:
        # Chromium exposes a heading, a landmark and often a link as a plain
        # TextControl, and LocalizedControlType is translated ("nagłówek" on a
        # Polish system), so the ARIA role is the only language-independent
        # signal there is.
        aria = _aria_role(control)
        if aria in _ARIA_TO_ROLE:
            role = _ARIA_TO_ROLE[aria]
        value = _uia_value(control)
        if not name and not value and role not in _ALWAYS_KEEP_ROLES:
            continue
        if role == C.ROLE_TEXT and not _visible_text(name):
            continue
        level = _uia_level(control)
        if aria == "heading" or role == C.ROLE_HEADING:
            role = C.ROLE_HEADING
            level = level or _heading_level_hint(control) or 1
        node = VNode(name=name, role=role, value=value, source="uia",
                     element=control, rect=_uia_rect(control),
                     states=_uia_states(control), level=level)
        nodes.append(node)
        if len(nodes) >= MAX_NODES:
            break
    return nodes


def _wrapper_worth_keeping(ctype, name) -> bool:
    """A group with a real caption is a landmark worth stopping on."""
    return ctype == "GroupControl" and bool(name)


def _visible_text(name) -> bool:
    """False for pure icon-font glyphs (private use area) -- read noise."""
    return bool("".join(c for c in (name or "")
                        if not (0xE000 <= ord(c) <= 0xF8FF)).strip())


def _uia_rect(control) -> tuple:
    try:
        r = control.BoundingRectangle
        return (int(r.left), int(r.top), int(r.right), int(r.bottom))
    except Exception:
        return ()


def _uia_value(control) -> str:
    for getter in ("GetValuePattern", "GetRangeValuePattern"):
        try:
            pattern = getattr(control, getter)()
        except Exception:
            continue
        if pattern is None:
            continue
        try:
            value = pattern.Value
        except Exception:
            continue
        if value not in (None, ""):
            return str(value)
    return ""


def _uia_states(control) -> tuple:
    states = []
    try:
        if not control.IsEnabled:
            states.append(C.STATE_UNAVAILABLE)
    except Exception:
        pass
    try:
        pattern = control.GetTogglePattern()
        if pattern is not None:
            states.append({0: C.STATE_UNCHECKED, 1: C.STATE_CHECKED}.get(
                int(pattern.ToggleState), C.STATE_PARTIAL))
    except Exception:
        pass
    try:
        pattern = control.GetSelectionItemPattern()
        if pattern is not None and pattern.IsSelected:
            states.append(C.STATE_SELECTED)
    except Exception:
        pass
    return tuple(states)


def _uia_level(control) -> int:
    """The UIA hierarchy Level property (the heading level for ARIA headings)."""
    try:
        value = control.GetPropertyValue(_UIA_PROP_LEVEL)
        return int(value) if value else 0
    except Exception:
        return 0


def _aria_role(control) -> str:
    """The element's ARIA role, lower-cased ('' when it has none)."""
    try:
        value = control.GetPropertyValue(_UIA_PROP_ARIAROLE)
        return (value or "").strip().lower()
    except Exception:
        return ""


def _heading_level_hint(control) -> int:
    """Heading level from the localized type or the automation id (h1 .. h6)."""
    try:
        localized = (control.LocalizedControlType or "").lower()
        for i in range(1, 7):
            if f"level {i}" in localized or f"heading {i}" in localized:
                return i
        aid = control.AutomationId or ""
        if len(aid) == 2 and aid[0] in "Hh" and aid[1].isdigit():
            return int(aid[1])
    except Exception:
        pass
    return 0


def build_ia2(hwnd) -> List[VNode]:
    """Flatten a web document through IAccessible2 (Chromium / Gecko).

    The page lives in a separate render fragment that a downward UIA walk of the
    window does not reach, so when :func:`build_uia` comes back with just the
    empty document wrapper this is what actually has the content.
    """
    try:
        from titan_access import ia2
    except Exception:
        return []
    try:
        raw = ia2.build_document_nodes(hwnd) if hwnd else []
    except Exception as e:
        print(f"[TitanAccess] virtual_buffer: IA2 build failed: {e}")
        return []
    nodes = []
    for item in raw or []:
        role = (item.get("role") or "").strip() or C.ROLE_TEXT
        nodes.append(VNode(name=(item.get("name") or "").strip(), role=role,
                           level=int(item.get("level") or 0), source="ia2",
                           hwnd=hwnd))
    return nodes


# =========================================================================== #
# Tier 2: MSAA / IAccessible (legacy applications)
# =========================================================================== #
def build_msaa(hwnd, deadline=None) -> List[VNode]:
    """Flatten the IAccessible tree of *hwnd*.

    This is the tier that makes old programs readable: Windows itself proxies
    the standard controls, so a dialog that exposes no UI Automation at all
    still reports its buttons, edits, list items and their state through oleacc.
    """
    if not _IS_WINDOWS or not hwnd:
        return []
    try:
        from titan_access import msaa_focus as msaa
    except Exception:
        return []
    root = msaa.object_from_window(hwnd)
    if root is None:
        return []
    nodes: List[VNode] = []
    _walk_msaa(msaa, root, hwnd, nodes, 0, deadline)
    return nodes


def _walk_msaa(msaa, acc, hwnd, nodes, depth, deadline):
    if depth > MAX_DEPTH or len(nodes) >= MAX_NODES:
        return
    if deadline and time.time() > deadline:
        return
    for child_acc, child_id in msaa.accessible_children(acc):
        if len(nodes) >= MAX_NODES:
            return
        if deadline and time.time() > deadline:
            return
        target = child_acc if child_acc is not None else acc
        cid = 0 if child_acc is not None else child_id
        info = msaa.describe_child(target, cid)
        if info is None:
            continue
        role = info.get("role", C.ROLE_UNKNOWN)
        name = info.get("name", "")
        states = tuple(info.get("states", ()))
        if "offscreen" in states or C.STATE_UNAVAILABLE in states and not name:
            # Invisible content is not part of the document. A disabled control
            # WITH a name still is (the user needs to know it is there).
            if "offscreen" in states:
                continue
        keep = bool(name) or role in _ALWAYS_KEEP_ROLES
        if keep and role not in (C.ROLE_WINDOW, C.ROLE_PANE, C.ROLE_GROUP):
            nodes.append(VNode(
                name=name, role=role, value=info.get("value", ""),
                states=states, rect=info.get("rect", ()), source="msaa",
                acc=target, child_id=cid, hwnd=hwnd))
        # Only a real IAccessible (not a simple child id) has children of its own.
        if child_acc is not None:
            _walk_msaa(msaa, child_acc, hwnd, nodes, depth + 1, deadline)


# =========================================================================== #
# Tier 3: raw child windows (very old / custom applications)
# =========================================================================== #
def build_win32(hwnd, deadline=None) -> List[VNode]:
    """Build a document from the child-window tree alone.

    No accessibility of any kind is involved: every child window becomes an
    entry, its class decides the role and its window text the name. A nameless
    control (the usual case for an Edit) is labelled from the Static text
    nearest to its left or above it - the association a program written before
    accessibility existed never made, and the reason this tier exists at all
    rather than being left to OCR.
    """
    if not _IS_WINDOWS or not hwnd:
        return []
    raw = []
    for child in _child_windows(hwnd):
        if deadline and time.time() > deadline:
            break
        if not _is_visible(child):
            continue
        cls = window_class(child)
        if cls in _CLASS_SKIP:
            continue
        rect = window_rect(child)
        if rect and (rect[2] - rect[0] <= 0 or rect[3] - rect[1] <= 0):
            continue
        role = _CLASS_TO_ROLE.get(cls)
        text = window_text(child)
        if role is None:
            if cls == "button":
                role = _button_role(child)
            elif text:
                role = C.ROLE_TEXT
            else:
                continue
        raw.append((child, cls, role, text, rect))

    nodes: List[VNode] = []
    for i, (child, cls, role, text, rect) in enumerate(raw):
        name = text
        if not name and role in (C.ROLE_EDIT, C.ROLE_COMBOBOX, C.ROLE_LISTBOX,
                                 C.ROLE_SLIDER, C.ROLE_SPINNER, C.ROLE_TREE):
            name = _nearby_label(raw, i)
        if not name and role not in _ALWAYS_KEEP_ROLES:
            continue
        nodes.append(VNode(name=name, role=role, rect=rect, source="win32",
                           hwnd=child,
                           value=text if role == C.ROLE_EDIT and text != name else "",
                           states=_win32_states(child, cls)))
    return nodes


def _button_role(hwnd) -> str:
    """A ``Button`` class is a push button, a tick box, an option or a frame."""
    try:
        style = _user32.GetWindowLongW(hwnd, -16)  # GWL_STYLE
    except Exception:
        return C.ROLE_BUTTON
    kind = style & 0x0F
    if kind in (0x02, 0x03, 0x05, 0x06):          # (AUTO)CHECKBOX / 3STATE
        return C.ROLE_CHECKBOX
    if kind in (0x04, 0x09):                      # (AUTO)RADIOBUTTON
        return C.ROLE_RADIO
    if kind == 0x07:                              # GROUPBOX
        return C.ROLE_GROUP
    return C.ROLE_BUTTON


def _win32_states(hwnd, cls) -> tuple:
    states = []
    try:
        if not _user32.IsWindowEnabled(hwnd):
            states.append(C.STATE_UNAVAILABLE)
    except Exception:
        pass
    if cls == "button":
        try:
            # BM_GETCHECK = 0x00F0; BST_CHECKED = 1, BST_INDETERMINATE = 2.
            role = _button_role(hwnd)
            if role in (C.ROLE_CHECKBOX, C.ROLE_RADIO):
                checked = int(_user32.SendMessageW(hwnd, 0x00F0, 0, 0))
                states.append({0: C.STATE_UNCHECKED, 1: C.STATE_CHECKED}.get(
                    checked, C.STATE_PARTIAL))
        except Exception:
            pass
    return tuple(states)


def _nearby_label(raw, index) -> str:
    """The Static text that labels the control at *index*.

    Prefers the nearest text to its LEFT on the same row, then the nearest text
    ABOVE it - the two layouts every dialog since Windows 3.1 has used.
    """
    _, _, _, _, rect = raw[index]
    if not rect:
        # No geometry: fall back to the previous static in z-order, which is
        # how dialog templates are almost always ordered.
        for j in range(index - 1, max(-1, index - 4), -1):
            if raw[j][2] == C.ROLE_TEXT and raw[j][3]:
                return raw[j][3]
        return ""
    left, top, _right, bottom = rect
    mid = (top + bottom) / 2.0
    best_left = best_above = None
    for j, (_h, _c, role, text, other) in enumerate(raw):
        if j == index or role != C.ROLE_TEXT or not text or not other:
            continue
        o_left, o_top, o_right, o_bottom = other
        if o_bottom >= top and o_top <= bottom and o_right <= left + 8:
            distance = left - o_right
            if best_left is None or distance < best_left[0]:
                best_left = (distance, text)
        elif o_bottom <= top + 4 and abs(o_left - left) < 60:
            distance = top - o_bottom
            if best_above is None or distance < best_above[0]:
                best_above = (distance, text)
    if best_left and best_left[0] < 400:
        return best_left[1]
    if best_above and best_above[0] < 60:
        return best_above[1]
    del mid
    return ""


# =========================================================================== #
# Tier 4: OCR (AI), via ocr_assist
# =========================================================================== #
def build_ocr(hwnd, on_status=None) -> List[VNode]:
    """Read the window as a picture and turn what the AI read into nodes.

    Returns an empty list (never raises) when AI features are off, no vision
    provider is configured, or the reading failed - the caller then simply has
    no document, which is the honest answer.
    """
    try:
        from titan_access import ocr_assist
    except Exception as e:
        if _DBG:
            print(f"[TitanAccess][vbuf] ocr_assist unavailable: {e}")
        return []
    try:
        return ocr_assist.build_nodes(hwnd, VNode, on_status=on_status)
    except Exception as e:
        print(f"[TitanAccess] virtual_buffer: OCR build failed: {e}")
        return []


# =========================================================================== #
# The tiered build
# =========================================================================== #
def build_for_window(hwnd=0, allow_ocr=True, on_status=None,
                     prefer=None) -> VirtualDocument:
    """Build the best virtual document available for *hwnd*.

    ``prefer`` forces a single tier ('uia' / 'msaa' / 'win32' / 'ocr'); by
    default every tier is tried in order of trust until one produces a usable
    document. ``allow_ocr`` gates the AI tier, which is the only one that sends
    anything anywhere.
    """
    hwnd = int(hwnd or foreground_hwnd())
    doc = VirtualDocument(hwnd=hwnd, title=window_text(hwnd))
    if not hwnd:
        return doc
    deadline = time.time() + BUILD_BUDGET_S
    tiers = []
    if prefer:
        tiers = [prefer]
    else:
        tiers = ["uia", "msaa", "win32"]
        if allow_ocr:
            tiers.append("ocr")
    for tier in tiers:
        try:
            nodes = _build_tier(tier, hwnd, deadline, on_status)
        except Exception as e:
            print(f"[TitanAccess] virtual_buffer: {tier} build failed: {e}")
            nodes = []
        if _DBG:
            print(f"[TitanAccess][vbuf] tier={tier} nodes={len(nodes)}", flush=True)
        if len(nodes) >= MIN_USEFUL_NODES or (nodes and tier == prefer):
            doc.nodes = nodes
            doc.source = tier
            break
        deadline = max(deadline, time.time() + 2.0)
    doc.signature = signature_for(hwnd, doc)
    doc.built_at = time.time()
    return doc


def _build_tier(tier, hwnd, deadline, on_status):
    if tier == "uia":
        return build_uia(_uia_root(hwnd), deadline)
    if tier == "msaa":
        return build_msaa(hwnd, deadline)
    if tier == "win32":
        return build_win32(hwnd, deadline)
    if tier == "ocr":
        return build_ocr(hwnd, on_status=on_status)
    return []


def _uia_root(hwnd):
    try:
        import uiautomation as auto
    except Exception:
        return None
    try:
        return auto.ControlFromHandle(hwnd) if hwnd else auto.GetForegroundControl()
    except Exception:
        return None


def signature_for(hwnd, doc=None) -> tuple:
    """A cheap fingerprint of "the screen the document was built from".

    Used to notice that the window changed (a new dialog, a new page, a new
    tab) so the buffer is rebuilt instead of navigating a document that is no
    longer on screen. Deliberately cheap: no tree walk.
    """
    return (int(hwnd or 0), window_text(hwnd), window_rect(hwnd),
            len(doc.nodes) if doc is not None else -1)


def looks_stale(doc: VirtualDocument, max_age=None) -> bool:
    """True when *doc* should be rebuilt before it is navigated again."""
    if doc is None or not doc.nodes:
        return True
    current = signature_for(doc.hwnd, doc)
    # Compare everything except the node count (which only this document knows).
    if current[:3] != doc.signature[:3]:
        return True
    if max_age is not None and (time.time() - doc.built_at) > max_age:
        return True
    return False


# =========================================================================== #
# Acting on a node
# =========================================================================== #
def focus_node(node: VNode) -> bool:
    """Move the real keyboard focus to *node* (best effort)."""
    if node is None:
        return False
    try:
        if node.source == "uia" and node.element is not None:
            node.element.SetFocus()
            return True
        if node.source == "msaa" and node.acc is not None:
            # accSelect(SELFLAG_TAKEFOCUS | SELFLAG_TAKESELECTION)
            node.acc.accSelect(3, node.child_id)
            return True
        if node.source == "win32" and node.hwnd:
            _user32.SetFocus(node.hwnd)
            return True
    except Exception:
        return False
    return False


def activate(node: VNode, screen=None) -> bool:
    """Press / toggle / select *node*, whichever tier produced it."""
    if node is None:
        return False
    handler = {
        "uia": _activate_uia,
        "msaa": _activate_msaa,
        "win32": _activate_win32,
        "ocr": _activate_ocr,
    }.get(node.source)
    if handler is None:
        return False
    try:
        return bool(handler(node, screen))
    except Exception as e:
        if _DBG:
            print(f"[TitanAccess][vbuf] activate failed: {e}")
        return False


def _activate_uia(node, _screen=None):
    element = node.element
    if element is None:
        return False
    for getter, call in (("GetInvokePattern", "Invoke"),
                         ("GetTogglePattern", "Toggle"),
                         ("GetSelectionItemPattern", "Select"),
                         ("GetExpandCollapsePattern", "Expand")):
        try:
            pattern = getattr(element, getter)()
        except Exception:
            continue
        if pattern is None:
            continue
        try:
            getattr(pattern, call)()
            return True
        except Exception:
            continue
    # Nothing invokable: focus it and press Enter, as a user would.
    try:
        element.SetFocus()
    except Exception:
        return False
    return _press_enter()


def _activate_msaa(node, _screen=None):
    acc = node.acc
    if acc is None:
        return False
    try:
        acc.accDoDefaultAction(node.child_id)
        return True
    except Exception:
        pass
    if focus_node(node):
        return _press_enter()
    return False


def _activate_win32(node, _screen=None):
    hwnd = node.hwnd
    if not hwnd:
        return False
    if node.role in (C.ROLE_BUTTON, C.ROLE_CHECKBOX, C.ROLE_RADIO,
                     C.ROLE_SPLIT_BUTTON):
        try:
            _user32.SetFocus(hwnd)
            _user32.SendMessageW(hwnd, 0x00F5, 0, 0)   # BM_CLICK
            return True
        except Exception:
            pass
    if focus_node(node):
        return True
    return _click_centre(node)


def _activate_ocr(node, screen=None):
    from titan_access import ocr_assist
    return ocr_assist.activate(node, screen)


def _press_enter() -> bool:
    if not _IS_WINDOWS:
        return False
    try:
        _user32.keybd_event(0x0D, 0, 0, 0)
        _user32.keybd_event(0x0D, 0, 0x0002, 0)
        return True
    except Exception:
        return False


def _click_centre(node) -> bool:
    """Click the middle of a node's rectangle (last resort, win32 tier only)."""
    centre = node.centre
    if centre is None or not _IS_WINDOWS:
        return False
    x, y = centre
    try:
        old = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(old))
        _user32.SetCursorPos(int(x), int(y))
        _user32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
        _user32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
        _user32.SetCursorPos(int(old.x), int(old.y))
        return True
    except Exception:
        return False
