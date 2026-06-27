# -*- coding: utf-8 -*-
"""Browse mode (virtual buffer) for web documents.

Python port of ``ScreenReader/BrowseMode/BrowseModeHandler.cs`` together with a
simplified virtual buffer (a flat, in-order list of the document's accessible
elements, inspired by NVDA's ``virtualBuffers`` / ``browseMode``).

When focus enters a browser document, browse mode becomes active. In browse mode
the document is read as a flat buffer: arrow up/down step through buffer nodes,
single letters jump by element type (``h`` headings, ``k`` links, ``b`` buttons,
... see :mod:`titan_access.quick_nav`), Shift reverses direction. Pass-through
("form" / "focus" mode) hands keys back to the page so the user can type into
fields.

The buffer is built by walking the UI Automation control tree from the document
root via the vendored ``uiautomation`` package; building is bounded (depth / node
count) so a huge page never stalls. If the buffer cannot be built the handler
degrades gracefully: :meth:`handle_key` returns ``False`` and the keys pass
through unchanged.

# LOCALE KEYS TO ADD: browse.browseMode = Browse mode
# LOCALE KEYS TO ADD: browse.focusMode = Focus mode
# LOCALE KEYS TO ADD: browse.noNext = No next {0}
# LOCALE KEYS TO ADD: browse.noPrevious = No previous {0}
# LOCALE KEYS TO ADD: browse.documentStart = Start of document
# LOCALE KEYS TO ADD: browse.documentEnd = End of document
# LOCALE KEYS TO ADD: browse.emptyLine = Empty line
"""

import ctypes
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional

from titan_access.localization import L
from titan_access import localization as loc
from titan_access import quick_nav as qn
from titan_access.contracts import SND_CLICK, SND_CURSOR, SND_EDGE

# --- defensive UIA import (module must import even without UIA) ------------- #
try:
    import uiautomation as auto
    _UIA = True
except Exception as _e:  # pragma: no cover - degrades to "browse unavailable"
    print(f"[TitanAccess] browse_mode: uiautomation unavailable: {_e}")
    auto = None
    _UIA = False

# Browser process names that host a web document (lower-case, no extension).
_BROWSER_PROCESSES = {
    "chrome", "msedge", "firefox", "brave", "vivaldi", "opera", "chromium",
    "waterfox", "librewolf", "iexplore", "edge",
}

# Bounds for buffer construction so a giant page never stalls the hook thread.
_MAX_DEPTH = 25
_MAX_NODES = 4000

# Virtual key codes for the arrow keys.
_VK_LEFT, _VK_UP, _VK_RIGHT, _VK_DOWN = 0x25, 0x26, 0x27, 0x28


@dataclass
class _Node:
    """One element in the flat virtual buffer."""
    element: Any                      # live uiautomation Control
    name: str = ""
    control_type: str = ""            # uiautomation ControlTypeName
    localized_type: str = ""          # lower-cased LocalizedControlType / ItemStatus
    level: int = 0                    # heading level (0 = unknown)
    runtime_id: tuple = field(default_factory=tuple)


class BrowseModeHandler:
    """Browse-mode controller bound to the engine.

    Construction never touches UIA; the buffer is built lazily the first time a
    key is handled in an active browser document.
    """

    def __init__(self, engine):
        self.engine = engine
        self._pass_through = False
        self._nodes: List[_Node] = []
        self._index = -1
        self._char_pos = 0
        self._root_runtime_id: tuple = ()
        self._active_pid = 0

    # ==================================================================== #
    # Activation state
    # ==================================================================== #
    @property
    def is_active(self) -> bool:
        """True when focus is inside a web document / browser window."""
        if not _UIA:
            return False
        try:
            return self._foreground_is_browser()
        except Exception:
            return False

    @property
    def pass_through(self) -> bool:
        return self._pass_through

    def _foreground_is_browser(self) -> bool:
        pid = _foreground_pid()
        if pid and _process_name_for_pid(pid) in _BROWSER_PROCESSES:
            return True
        # Fall back to the focused object's owning process.
        obj = getattr(self.engine, "current_object", None)
        if obj is not None and getattr(obj, "process_id", 0):
            return _process_name_for_pid(obj.process_id) in _BROWSER_PROCESSES
        return False

    # ==================================================================== #
    # Mode toggle
    # ==================================================================== #
    def toggle_pass_through(self):
        """Switch between browse mode and focus (form) mode."""
        self._pass_through = not self._pass_through
        if self._pass_through:
            self.engine.play(SND_CLICK)
            self.engine.speak(L("browse.focusMode"))
        else:
            self.engine.play(SND_CURSOR)
            self.engine.speak(L("browse.browseMode"))

    # ==================================================================== #
    # Key handling
    # ==================================================================== #
    def handle_key(self, vk, key_name, ctrl, alt, shift) -> bool:
        """Handle a plain key in browse mode. Return True to consume it.

        In focus (pass-through) mode nothing is consumed. Otherwise: arrows step
        the buffer caret and single letters perform quick navigation. If the
        buffer cannot be built we return False so the key reaches the page.
        """
        if self._pass_through or not _UIA:
            return False

        # Arrow navigation (no modifiers other than handled here).
        if not ctrl and not alt:
            if vk == _VK_UP:
                return self._move_line(-1)
            if vk == _VK_DOWN:
                return self._move_line(+1)
            if vk == _VK_LEFT:
                return self._move_char(-1)
            if vk == _VK_RIGHT:
                return self._move_char(+1)

        # Single-letter / digit quick navigation (Ctrl/Alt are app shortcuts).
        if ctrl or alt:
            return False
        ch = _char_for_key(vk, key_name)
        if not ch:
            return False
        qn_type = qn.type_for_key(ch)
        if qn_type == qn.QuickNavType.NONE:
            return False
        if not self._ensure_buffer():
            return False
        self._quick_nav(qn_type, backward=shift)
        return True

    # ==================================================================== #
    # Virtual buffer construction
    # ==================================================================== #
    def _document_root(self):
        """Locate the document root element of the foreground browser window."""
        if not _UIA:
            return None
        try:
            hwnd = _foreground_hwnd()
            window = auto.ControlFromHandle(hwnd) if hwnd else auto.GetForegroundControl()
        except Exception:
            window = None
        if window is None:
            return None
        # Prefer the focused element's nearest Document ancestor; else search.
        try:
            focused = auto.GetFocusedControl()
        except Exception:
            focused = None
        doc = self._nearest_document(focused) if focused is not None else None
        if doc is None:
            doc = self._find_first(window, lambda c: _ctype(c) == "DocumentControl")
        return doc or window

    @staticmethod
    def _nearest_document(control):
        node = control
        depth = 0
        while node is not None and depth < 40:
            try:
                if _ctype(node) == "DocumentControl":
                    return node
                node = node.GetParentControl()
            except Exception:
                return None
            depth += 1
        return None

    def _ensure_buffer(self) -> bool:
        """(Re)build the buffer if the document changed or it is empty."""
        root = self._document_root()
        if root is None:
            return False
        rid = _runtime_id(root)
        if self._nodes and rid and rid == self._root_runtime_id:
            return True
        try:
            self._build_buffer(root)
        except Exception as e:
            print(f"[TitanAccess] browse_mode: buffer build failed: {e}")
            self._nodes = []
        self._root_runtime_id = rid
        self._index = 0 if self._nodes else -1
        self._char_pos = 0
        return bool(self._nodes)

    def _build_buffer(self, root):
        nodes: List[_Node] = []
        try:
            walker = auto.WalkControl(root, includeTop=False, maxDepth=_MAX_DEPTH)
        except Exception:
            walker = None
        if walker is None:
            self._nodes = nodes
            return
        for control, _depth in walker:
            try:
                ctype = _ctype(control)
                name = (control.Name or "").strip()
                localized = (_localized(control) or "").lower()
            except Exception:
                continue
            # Keep interactive controls always; keep text only if it has content.
            interactive = ctype not in ("TextControl", "")
            if not interactive and not name:
                continue
            if ctype == "TextControl":
                # Drop pure icon-font glyphs (private-use area) — read noise.
                visible = "".join(c for c in name
                                  if not (0xE000 <= ord(c) <= 0xF8FF))
                if not visible.strip():
                    continue
            node = _Node(element=control, name=name, control_type=ctype,
                         localized_type=localized, level=_heading_level(control),
                         runtime_id=_runtime_id(control))
            nodes.append(node)
            if len(nodes) >= _MAX_NODES:
                break
        self._nodes = nodes

    # ==================================================================== #
    # Quick navigation
    # ==================================================================== #
    def _quick_nav(self, qn_type, backward):
        start = self._index if self._index >= 0 else 0
        rng = (range(start - 1, -1, -1) if backward
               else range(start + 1, len(self._nodes)))
        for i in rng:
            if self._matches(self._nodes[i], qn_type):
                self._index = i
                self._char_pos = 0
                self._announce_node(self._nodes[i], qn_type)
                return
        # Nothing found in that direction.
        label = qn.type_label(qn_type)
        self.engine.play(SND_EDGE)
        self.engine.speak(L("browse.noPrevious", label) if backward
                          else L("browse.noNext", label))

    def _matches(self, node, qn_type) -> bool:
        # Headings are recognised by localized type / heading level.
        if qn.is_heading(qn_type):
            if "heading" not in node.localized_type and node.level <= 0:
                return False
            want = qn.heading_level(qn_type)
            return want == 0 or node.level == want
        ct = qn.CONTROL_TYPE_MATCH.get(qn_type, ())
        if node.control_type in ct:
            # Paragraph also requires actual text content.
            if qn_type == qn.QuickNavType.PARAGRAPH and not node.name:
                return False
            return True
        aria = qn.ARIA_MATCH.get(qn_type, ())
        return any(token in node.localized_type for token in aria)

    # ==================================================================== #
    # Linear (arrow) navigation
    # ==================================================================== #
    def _move_line(self, delta) -> bool:
        if not self._ensure_buffer():
            return False
        new = self._index + delta
        if new < 0:
            self.engine.play(SND_EDGE)
            self.engine.speak(L("browse.documentStart"))
            return True
        if new >= len(self._nodes):
            self.engine.play(SND_EDGE)
            self.engine.speak(L("browse.documentEnd"))
            return True
        self._index = new
        self._char_pos = 0
        self._announce_node(self._nodes[new])
        return True

    def _move_char(self, delta) -> bool:
        if not self._ensure_buffer() or not (0 <= self._index < len(self._nodes)):
            return False
        text = self._nodes[self._index].name
        if not text:
            self.engine.speak(L("browse.emptyLine"))
            return True
        new = self._char_pos + delta
        if new < 0 or new >= len(text):
            self.engine.play(SND_EDGE)
            self.engine.speak(L("browse.documentStart") if delta < 0
                              else L("browse.documentEnd"))
            return True
        self._char_pos = new
        self.engine.speak(loc.character_announcement(text[new], use_phonetic=False))
        return True

    # ==================================================================== #
    # Announcement
    # ==================================================================== #
    def _announce_node(self, node, qn_type=None):
        # Move real focus to the element when possible (best-effort).
        try:
            node.element.SetFocus()
        except Exception:
            pass
        # Preferred path: convert to AccessibleObject and use the rich announcer.
        ao = self._to_accessible(node.element)
        if ao is not None:
            try:
                self.engine.announce_object(ao, for_navigation=True)
                return
            except Exception:
                pass
        # Fallback: name + type label (+ heading level).
        label = qn.type_label(qn_type) if qn_type is not None else node.localized_type
        if qn_type is not None and qn.is_heading(qn_type) and node.level > 0:
            label = L("quickNav.headingLevel", node.level)
        text = f"{node.name}, {label}" if node.name and label else (node.name or label)
        self.engine.play(SND_CURSOR)
        self.engine.speak(text)

    def _to_accessible(self, element):
        provider = getattr(self.engine, "provider", None)
        if provider is None:
            return None
        for meth in ("element_to_object", "object_from_element"):
            fn = getattr(provider, meth, None)
            if fn is None:
                continue
            try:
                return fn(element)
            except Exception:
                return None
        return None


# =========================================================================== #
# Win32 helpers (defensive; never raise)
# =========================================================================== #
def _foreground_hwnd() -> int:
    try:
        return int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        return 0


def _foreground_pid() -> int:
    try:
        import ctypes.wintypes as wt
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = wt.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def _process_name_for_pid(pid: int) -> str:
    if not pid:
        return ""
    try:
        import ctypes.wintypes as wt
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        k = ctypes.windll.kernel32
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
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


# =========================================================================== #
# UIA accessor helpers (tolerant of missing properties)
# =========================================================================== #
def _ctype(control) -> str:
    try:
        return control.ControlTypeName or ""
    except Exception:
        return ""


def _localized(control) -> str:
    try:
        val = control.LocalizedControlType or ""
        if not val:
            val = control.ItemStatus or ""
        return val
    except Exception:
        return ""


def _runtime_id(control) -> tuple:
    try:
        return tuple(control.GetRuntimeId() or ())
    except Exception:
        return ()


def _char_for_key(vk, key_name) -> str:
    """Resolve a single navigation character from the virtual key / name."""
    try:
        if 0x41 <= vk <= 0x5A:           # A-Z
            return chr(vk).lower()
        if 0x30 <= vk <= 0x39:           # 0-9 (top row)
            return chr(vk)
        if 0x60 <= vk <= 0x69:           # numpad 0-9
            return chr(vk - 0x60 + ord('0'))
    except Exception:
        pass
    if key_name and len(key_name) == 1:
        return key_name.lower()
    return ""


def _heading_level(control) -> int:
    """Best-effort heading level from LocalizedControlType / AutomationId."""
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
