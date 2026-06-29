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
# LOCALE KEYS TO ADD: browse.webPage = web page
"""

import ctypes
import os
_DBG = bool(os.environ.get("TITAN_ACCESS_DEBUG"))
from dataclasses import dataclass, field
from typing import Any, List, Optional

from titan_access.localization import L
from titan_access import localization as loc
from titan_access import quick_nav as qn
from titan_access import presentation as pres
from titan_access.contracts import SND_CLICK, SND_CURSOR, SND_EDGE

# --- defensive UIA import (module must import even without UIA) ------------- #
try:
    import uiautomation as auto
    _UIA = True
except Exception as _e:  # pragma: no cover - degrades to "browse unavailable"
    print(f"[TitanAccess] browse_mode: uiautomation unavailable: {_e}")
    auto = None
    _UIA = False

# Browser / web-host process names that host a web document (lower-case, no ext).
_BROWSER_PROCESSES = {
    "chrome", "msedge", "firefox", "brave", "vivaldi", "opera", "chromium",
    "waterfox", "librewolf", "iexplore", "edge",
    # Embedded web hosts (WebView2 / CEF / generic webview).
    "msedgewebview2", "webview2", "cef", "cefclient",
}
# UIA FrameworkId values that mean "this element is web content" — covers
# WebView2 and Electron apps whose own process name is not a known browser.
_WEB_FRAMEWORKS = {"chrome", "gecko", "webview", "edge", "blink"}

# Window classes that host a rendered web document. Chromium (Chrome / Edge /
# WebView2 / CEF / Electron / Brave / Opera / Vivaldi) all render content in a
# ``Chrome_RenderWidgetHostHWND`` child window; Firefox/Gecko use the Mozilla
# classes. Detecting these makes browse mode engage for web content embedded in
# a host app or dialog (where the foreground process is NOT a browser and the
# focus snapshot may arrive via MSAA without a framework id / process id).
_WEB_WINDOW_CLASSES = {
    "chrome_renderwidgethosthwnd",   # Chromium (all variants + WebView2 / CEF)
    "mozillawindowclass",            # Firefox / Gecko
    "mozillacontentwindowclass",
}

# Bounds for buffer construction so a giant page never stalls the hook thread.
_MAX_DEPTH = 25
_MAX_NODES = 4000

# Minimum bounding-rectangle area (px^2) for a DocumentControl to count as a web
# *content* viewport rather than a small browser-chrome document (omnibox list,
# etc.). ~316x316; the page viewport is far larger, chrome documents far smaller.
_MIN_CONTENT_AREA = 100000

# Virtual key codes for the arrow keys.
_VK_LEFT, _VK_UP, _VK_RIGHT, _VK_DOWN = 0x25, 0x26, 0x27, 0x28


@dataclass
class _Node:
    """One element in the flat virtual buffer."""
    element: Any                      # live uiautomation Control (None for IA2 nodes)
    name: str = ""
    control_type: str = ""            # uiautomation ControlTypeName
    localized_type: str = ""          # lower-cased LocalizedControlType / ItemStatus
    level: int = 0                    # heading level (0 = unknown)
    runtime_id: tuple = field(default_factory=tuple)
    role: str = ""                    # Titan role key (set for IA2-sourced nodes)


# QuickNavType -> Titan role keys, for IA2-sourced nodes that have no UIA
# ControlTypeName. Headings are matched by role/level separately.
_QN_ROLE_MATCH = {
    qn.QuickNavType.LINK: ("link",),
    qn.QuickNavType.UNVISITED_LINK: ("link",),
    qn.QuickNavType.VISITED_LINK: ("link",),
    qn.QuickNavType.BUTTON: ("button", "split_button"),
    qn.QuickNavType.EDIT_FIELD: ("edit", "document"),
    qn.QuickNavType.COMBO_BOX: ("combobox",),
    qn.QuickNavType.CHECKBOX: ("checkbox",),
    qn.QuickNavType.RADIO_BUTTON: ("radio",),
    qn.QuickNavType.LIST: ("list",),
    qn.QuickNavType.LIST_ITEM: ("listitem",),
    qn.QuickNavType.TABLE: ("table", "grid"),
    qn.QuickNavType.GRAPHIC: ("image",),
    qn.QuickNavType.LANDMARK: ("group",),
    qn.QuickNavType.FORM_FIELD: ("edit", "combobox", "checkbox", "radio",
                                 "button"),
}


class BrowseModeHandler:
    """Browse-mode controller bound to the engine.

    Construction never touches UIA; the buffer is built lazily the first time a
    key is handled in an active browser document.
    """

    def __init__(self, engine):
        self.engine = engine
        self._pass_through = False
        self._manual_override = False   # user pressed the toggle; pause auto-switch
        self._nodes: List[_Node] = []
        self._index = -1
        self._char_pos = 0
        self._root_runtime_id: tuple = ()
        self._active_pid = 0
        self._was_web = False           # were we inside a web document last focus?
        self._last_content_doc = None   # last good web content document (Control)

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
        obj = getattr(self.engine, "current_object", None)
        if obj is not None:
            # Owning process is a known browser / web host.
            if getattr(obj, "process_id", 0) and \
                    _process_name_for_pid(obj.process_id) in _BROWSER_PROCESSES:
                return True
            # Or the focused element is web content (WebView2 / Electron, whose
            # own process name is not a browser).
            fw = (getattr(obj, "framework_id", "") or "").lower()
            if fw in _WEB_FRAMEWORKS:
                return True
        # Last resort: the foreground window hosts a rendered web document. This
        # catches web content embedded in a host app / dialog (WebView2, CEF) and
        # MSAA-delivered focus, where the process-name and framework checks above
        # have nothing to match against.
        if _foreground_hosts_web_document():
            return True
        return False

    # ==================================================================== #
    # Mode toggle
    # ==================================================================== #
    def toggle_pass_through(self):
        """Switch between browse mode and focus (form) mode (manual override)."""
        self._pass_through = not self._pass_through
        self._manual_override = True   # don't let auto-switch fight the user
        if self._pass_through:
            self.engine.play(SND_CLICK)
            self.engine.speak(L("browse.focusMode"))
        else:
            self.engine.play(SND_CURSOR)
            self.engine.speak(L("browse.browseMode"))

    # Roles that should auto-switch the document into focus (pass-through) mode,
    # so typing / arrowing edits the field instead of driving quick navigation
    # (NVDA's automatic focus mode).
    _FOCUS_MODE_ROLES = {"edit", "password", "combobox", "spinner", "slider"}

    def update_for_focus(self, obj):
        """Auto-switch browse vs focus mode when focus moves inside a web
        document, mirroring NVDA: editable / form controls => focus mode, other
        content => browse mode. A manual toggle pauses auto-switching until focus
        moves to a control of the opposite kind."""
        active = self.is_active
        if _DBG:
            print(f"[TitanAccess][browse] update_for_focus role="
                  f"{getattr(obj,'role',None)!r} active={active} "
                  f"pass_through={self._pass_through} was_web={self._was_web}",
                  flush=True)
        if not _UIA or not active:
            self._manual_override = False
            self._was_web = False
            return
        # Announce crossing into a web document. Without this the entry is read
        # with the container's raw role ("dialog" / "pane") and the user never
        # learns the page is a browsable web document — the auto mode-switch below
        # stays silent because browse mode is already the default (no flip).
        if not self._was_web:
            self._was_web = True
            self._announce_web_entry(obj)
        want_focus = obj is not None and obj.role in self._FOCUS_MODE_ROLES
        if want_focus == self._pass_through:
            # Already in the right mode; a matching focus clears the manual hold.
            self._manual_override = False
            return
        if self._manual_override:
            # User forced a mode; respect it until the focus kind flips.
            self._manual_override = False
            return
        self._pass_through = want_focus
        if want_focus:
            self.engine.play(SND_CLICK)
            self.engine.speak(L("browse.focusMode"))
        else:
            self.engine.play(SND_CURSOR)
            self.engine.speak(L("browse.browseMode"))

    def _announce_web_entry(self, obj):
        """Announce that focus has entered a browsable web document.

        Spoken as "<page title>, web page" so the user knows arrows / single
        letters now drive the virtual buffer instead of tabbing a dialog. The
        title is the foreground window text (browser tab title), falling back to
        the focused object's name."""
        title = _foreground_window_title()
        if not title and obj is not None:
            title = (getattr(obj, "name", "") or "").strip()
        page = L("browse.webPage")
        self.engine.play(SND_CURSOR)
        self.engine.speak(f"{title}, {page}" if title else page, interrupt=False)

    # ==================================================================== #
    # Key handling
    # ==================================================================== #
    def handle_key(self, vk, key_name, ctrl, alt, shift) -> bool:
        """Handle a plain key in browse mode. Return True to consume it.

        In focus (pass-through) mode nothing is consumed. Otherwise: arrows step
        the buffer caret and single letters perform quick navigation. If the
        buffer cannot be built we return False so the key reaches the page.
        """
        if _DBG and key_name in ("up", "down", "left", "right") and not ctrl and not alt:
            print(f"[TitanAccess][browse] handle_key {key_name} "
                  f"pass_through={self._pass_through} active={self.is_active} "
                  f"nodes={len(self._nodes)}", flush=True)
        if self._pass_through or not _UIA:
            return False

        # Arrow navigation (no modifiers other than handled here).
        if not ctrl and not alt:
            if key_name == "enter":
                return self._activate_current()
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

    def quick_nav_by_char(self, ch, backward=False) -> bool:
        """Public entry used by the dial: jump to the next/previous element of
        the quick-nav type bound to *ch* (e.g. ``b`` buttons, ``h`` headings).

        Returns ``False`` when no browse buffer can be built (e.g. focus is not
        inside a web document), so the caller can announce that the category is
        not available here instead of failing silently.
        """
        if not _UIA:
            return False
        qn_type = qn.type_for_key((ch or "").lower())
        if qn_type == qn.QuickNavType.NONE:
            return False
        if not self._ensure_buffer():
            return False
        self._quick_nav(qn_type, backward=backward)
        return True

    # ==================================================================== #
    # Activation + say all
    # ==================================================================== #
    def _activate_current(self) -> bool:
        """Activate the node at the buffer caret (Enter): Invoke / Toggle, or
        focus it and press Enter. Returns True (handled)."""
        if not (0 <= self._index < len(self._nodes)):
            return False
        element = self._nodes[self._index].element
        ok = False
        for getter, call in (("GetInvokePattern", "Invoke"),
                             ("GetTogglePattern", "Toggle"),
                             ("GetSelectionItemPattern", "Select")):
            try:
                pattern = getattr(element, getter)()
                if pattern is not None:
                    getattr(pattern, call)()
                    ok = True
                    break
            except Exception:
                continue
        if not ok:
            try:
                element.SetFocus()
                ctypes.windll.user32.keybd_event(0x0D, 0, 0, 0)
                ctypes.windll.user32.keybd_event(0x0D, 0, 0x0002, 0)
                ok = True
            except Exception:
                ok = False
        self.engine.play(SND_CLICK if ok else SND_EDGE)
        return True

    def say_all(self) -> bool:
        """Read continuously from the buffer caret to the end (NVDA say all).

        Each node's name is spoken in order; the user interrupts by pressing a
        key (which stops speech through the normal stop path). Runs on a thread
        so it never blocks the hook / focus thread.
        """
        if not self._ensure_buffer():
            return False
        import threading

        def _run():
            i = self._index if self._index >= 0 else 0
            for j in range(i, len(self._nodes)):
                node = self._nodes[j]
                text = node.name
                if not text:
                    continue
                self._index = j
                # interrupt=False so lines queue back-to-back like say-all.
                self.engine.speak(text, interrupt=(j == i))
                # Pace by the speech adapter's own segment wait when available.
                sp = getattr(self.engine, "speech", None)
                if sp is not None and hasattr(sp, "_wait_for_segment"):
                    try:
                        sp._wait_for_segment(text, getattr(sp, "_seq_id", 0))
                        continue
                    except Exception:
                        pass
                import time as _t
                _t.sleep(min(2.5, 0.28 + len(text) / 16.0))

        threading.Thread(target=_run, daemon=True).start()
        return True

    # ==================================================================== #
    # Virtual buffer construction
    # ==================================================================== #
    def _document_root(self):
        """Locate the **web content** document of the foreground browser window.

        The browser chrome (address bar, toolbars, menus) is itself web UI in
        modern Chromium/Edge, so several ``DocumentControl`` elements exist: the
        page viewport AND small chrome documents (the omnibox suggestion list,
        etc.). We must return the *content* document, otherwise browse mode reads
        the browser menu instead of the page. Strategy: use the focused element's
        nearest document only when it is a real content document; otherwise pick
        the largest web document in the window."""
        if not _UIA:
            return None
        try:
            hwnd = _foreground_hwnd()
            window = auto.ControlFromHandle(hwnd) if hwnd else auto.GetForegroundControl()
        except Exception:
            window = None
        # 1) Focus inside a real content document? Walk UP to it. This is the
        #    only reliable route in modern Chromium/Edge: the page lives in a
        #    separate renderer fragment that a downward tree walk from the window
        #    does not reach, but GetParentControl from a focused content element
        #    climbs straight to its document. (Also handles iframes the user
        #    tabbed into.) Remember it so a later chrome focus can still find it.
        try:
            focused = auto.GetFocusedControl()
        except Exception:
            focused = None
        doc = self._nearest_document(focused) if focused is not None else None
        if self._is_content_document(doc):
            self._last_content_doc = doc
            return doc
        # 2) Try a (bounded) downward search for the largest web document. This
        #    works in browsers that expose the document in the control tree
        #    (e.g. Firefox/Gecko) and is a harmless no-op where it does not.
        if window is not None:
            main = self._find_main_document(window)
            if self._is_content_document(main):
                self._last_content_doc = main
                return main
        # 3) Focus is on the browser chrome (toolbar / address bar / menu).
        #    Reuse the last content document if it is still alive, so the user can
        #    keep reading the page. NEVER fall back to the chrome window itself --
        #    that is what made browse mode read the browser menu instead of the
        #    page. When nothing valid is available, return None so the keys pass
        #    through to the browser rather than narrating its menus.
        last = getattr(self, "_last_content_doc", None)
        if last is not None and self._is_content_document(last):
            return last
        self._last_content_doc = None
        return None

    @staticmethod
    def _is_content_document(doc) -> bool:
        """True when *doc* is a real web *content* document (page viewport), not a
        small chrome document (omnibox dropdown) or a non-web document."""
        if doc is None:
            return False
        try:
            if _ctype(doc) != "DocumentControl":
                return False
            fw = (doc.FrameworkId or "").lower()
            if fw and fw not in _WEB_FRAMEWORKS:
                return False
            # A real page viewport covers a large area; the omnibox suggestion
            # list and other browser-chrome documents are small. (A dead document
            # from a navigated-away page reports a 0 area and is rejected too.)
            return _control_area(doc) >= _MIN_CONTENT_AREA
        except Exception:
            return False

    def _find_main_document(self, window):
        """Bounded BFS for the largest web ``DocumentControl`` under *window* —
        the page viewport, as opposed to the browser-chrome documents."""
        from collections import deque
        best = None
        best_area = 0
        queue = deque([(window, 0)])
        seen = 0
        while queue:
            node, depth = queue.popleft()
            if depth >= 24:
                continue
            try:
                children = node.GetChildren()
            except Exception:
                children = []
            for child in children or []:
                seen += 1
                if seen > 3000:
                    return best
                try:
                    if _ctype(child) == "DocumentControl":
                        fw = (child.FrameworkId or "").lower()
                        if not fw or fw in _WEB_FRAMEWORKS:
                            area = _control_area(child)
                            if area > best_area:
                                best_area, best = area, child
                        # Don't descend into a document; the outermost content
                        # document is what we want (and it's much faster).
                        continue
                except Exception:
                    pass
                queue.append((child, depth + 1))
        return best

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

    @staticmethod
    def _find_first(root, predicate, max_depth=24, max_nodes=2500):
        """Bounded breadth-first search for the first descendant of *root*
        satisfying *predicate*. Returns the matching ``Control`` or ``None``.

        Used to locate the web ``DocumentControl`` when focus is not currently
        inside it (e.g. focus is on the browser toolbar/address bar). Bounded by
        depth and node count so a huge UI never stalls the hook thread."""
        if root is None:
            return None
        from collections import deque
        queue = deque([(root, 0)])
        seen = 0
        while queue:
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue
            try:
                children = node.GetChildren()
            except Exception:
                children = []
            for child in children or []:
                seen += 1
                if seen > max_nodes:
                    return None
                try:
                    if predicate(child):
                        return child
                except Exception:
                    pass
                queue.append((child, depth + 1))
        return None

    def _ensure_buffer(self) -> bool:
        """(Re)build the buffer if the document changed or it is empty."""
        root = self._document_root()
        if _DBG:
            try:
                rn = None if root is None else (root.ControlTypeName, (root.Name or "")[:30])
            except Exception:
                rn = "?"
            print(f"[TitanAccess][browse] ensure_buffer root={rn} "
                  f"nodes={len(self._nodes)}", flush=True)
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
        # IA2 fallback: when UIA exposed nothing (common for Chromium/Gecko,
        # whose richest tree is IAccessible2), build the buffer from the IA2
        # document tree instead.
        if not self._nodes:
            self._build_ia2_buffer()
        self._root_runtime_id = rid
        self._index = 0 if self._nodes else -1
        self._char_pos = 0
        return bool(self._nodes)

    def _build_ia2_buffer(self):
        """Populate the buffer from the IAccessible2 web document (fallback)."""
        try:
            from titan_access import ia2
        except Exception:
            return
        try:
            hwnd = _foreground_hwnd()
            raw = ia2.build_document_nodes(hwnd) if hwnd else []
        except Exception as e:
            print(f"[TitanAccess] browse_mode: IA2 buffer failed: {e}")
            raw = []
        nodes = []
        for n in raw:
            nodes.append(_Node(
                element=None, name=n.get("name", ""),
                control_type="", localized_type=(n.get("role") or ""),
                level=int(n.get("level") or 0), role=n.get("role", "")))
        if nodes:
            self._nodes = nodes
            print(f"[TitanAccess] browse_mode: IA2 buffer built ({len(nodes)} nodes)")

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
                # Skip invisible / offscreen nodes (NVDA presentation filter).
                if pres.presentation_type(control) == pres.UNAVAILABLE:
                    continue
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
            # Heading detection must be language-independent: in Chromium the
            # heading (h1..h6 / role=heading) is exposed as a plain TextControl
            # whose only English-free signal is the ARIA role + UIA Level
            # property. (LocalizedControlType is translated -- "nagłówek" on a
            # Polish system -- so the old "heading" substring test never matched.)
            aria = _aria_role(control)
            level = _heading_level(control)
            role = ""
            if aria == "heading":
                role = "heading"
                level = level or _uia_level(control)
            node = _Node(element=control, name=name, control_type=ctype,
                         localized_type=localized, level=level,
                         runtime_id=_runtime_id(control), role=role)
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
        # Headings are recognised by localized type / heading level / role.
        if qn.is_heading(qn_type):
            is_heading = ("heading" in node.localized_type or node.level > 0
                          or node.role == "heading")
            if not is_heading:
                return False
            want = qn.heading_level(qn_type)
            return want == 0 or node.level == want
        # IA2-sourced nodes carry a Titan role instead of a UIA control type.
        if node.element is None and node.role:
            return node.role in _QN_ROLE_MATCH.get(qn_type, ())
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
        # IA2-sourced node (no live UIA Control): speak name + role (+ level)
        # with the cursor cue, since there is no element to announce richly.
        if node.element is None:
            self.engine.play(SND_CURSOR)
            parts = []
            if node.name:
                parts.append(node.name)
            if node.role == "heading" and node.level:
                parts.append(L("quickNav.headingLevel", node.level))
            elif node.role:
                parts.append(loc.role_label(node.role))
            self.engine.speak(", ".join(p for p in parts if p) or node.name)
            return
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


def _foreground_window_title() -> str:
    try:
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        if not hwnd:
            return ""
        n = u.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        return (buf.value or "").strip()
    except Exception:
        return ""


def _foreground_pid() -> int:
    try:
        import ctypes.wintypes as wt
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = wt.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


# Brief cache so the EnumChildWindows walk below does not run on every key /
# focus event. Keyed by foreground hwnd; (hwnd, time, result).
_web_doc_cache = (0, 0.0, False)


def _foreground_hosts_web_document() -> bool:
    """True when the foreground window contains a web-render child window.

    Enumerates the foreground window's descendants (``EnumChildWindows`` visits
    the whole subtree, not just direct children) looking for a class in
    :data:`_WEB_WINDOW_CLASSES`. Cached for a short interval per foreground
    window because it is consulted on every key press in browse mode.
    Fully guarded — any failure reports "no web document"."""
    global _web_doc_cache
    import time as _t
    try:
        hwnd = _foreground_hwnd()
    except Exception:
        return False
    if not hwnd:
        return False
    cached_hwnd, cached_at, cached_val = _web_doc_cache
    now = _t.time()
    if hwnd == cached_hwnd and (now - cached_at) < 0.5:
        return cached_val
    found = _enum_has_web_window(hwnd)
    _web_doc_cache = (hwnd, now, found)
    return found


def _enum_has_web_window(hwnd: int) -> bool:
    try:
        import ctypes.wintypes as wt
        user32 = ctypes.windll.user32
        result = {"hit": False}

        def _class(h):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, buf, 256)
            return (buf.value or "").lower()

        # The top-level window class can itself be a render-widget host.
        if _class(hwnd) in _WEB_WINDOW_CLASSES:
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

        def _enum(h, _l):
            try:
                if _class(h) in _WEB_WINDOW_CLASSES:
                    result["hit"] = True
                    return False   # stop enumeration
            except Exception:
                pass
            return True

        user32.EnumChildWindows(hwnd, WNDENUMPROC(_enum), 0)
        return result["hit"]
    except Exception:
        return False


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


def _control_area(control) -> int:
    """Bounding-rectangle area of *control* in px^2 (0 when unavailable)."""
    try:
        r = control.BoundingRectangle
        wdt = max(0, int(getattr(r, "right", 0)) - int(getattr(r, "left", 0)))
        hgt = max(0, int(getattr(r, "bottom", 0)) - int(getattr(r, "top", 0)))
        return wdt * hgt
    except Exception:
        return 0


# UIA property ids used for language-independent heading detection.
_UIA_PROP_ARIAROLE = 30101
_UIA_PROP_LEVEL = 30154


def _aria_role(control) -> str:
    """The element's ARIA role (e.g. ``heading``, ``button``), lower-cased.

    Language-independent (unlike LocalizedControlType). Empty when the element
    exposes no ARIA role / the property is unavailable."""
    try:
        val = control.GetPropertyValue(_UIA_PROP_ARIAROLE)
        return (val or "").strip().lower()
    except Exception:
        return ""


def _uia_level(control) -> int:
    """The UIA hierarchy Level property (heading level for ARIA headings)."""
    try:
        val = control.GetPropertyValue(_UIA_PROP_LEVEL)
        return int(val) if val else 0
    except Exception:
        return 0


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
