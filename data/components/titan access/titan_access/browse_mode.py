# -*- coding: utf-8 -*-
"""Document mode: a web page, or any application, read as a flat document.

Two modes share one implementation, because they are the same idea:

* **Browse mode** engages by itself inside a web document. Arrow keys walk the
  page, single letters jump by element type (``h`` headings, ``k`` links, ``b``
  buttons -- see :mod:`titan_access.quick_nav`), Shift reverses, and focus mode
  (pass-through) hands the keys back to the page so a form can be typed into.
  This is the NVDA behaviour users already expect on the web.

* **Scan mode** is the same document over an ORDINARY application, switched on
  and off by the user with the reader modifier + Space. The application's own
  interface becomes a virtual page: the same arrows, the same quick-navigation
  letters, the same Enter to press whatever the cursor is on. It is what makes a
  program navigable that cannot be tabbed through at all -- and, because the
  document is built by :mod:`titan_access.virtual_buffer`, it works on modern
  apps (UI Automation), on legacy Win32 / VB6 / Delphi programs (MSAA, then the
  raw child windows), and -- when the window answers nothing and Titan's AI
  features are on -- on what the AI reads off a picture of it.

The buffer itself is always a flat list of :class:`~titan_access.virtual_buffer.VNode`,
whichever source produced it, so navigation, quick navigation, announcement and
activation are written once.

CRITICAL, and the reason for :meth:`_dispatch`: :meth:`handle_key` runs on the
keyboard-hook thread, whose message loop services the global ``WH_KEYBOARD_LL``
hook. Building or walking the document there (thousands of cross-process COM
calls) blocks that loop, and once a low-level hook callback exceeds Windows'
``LowLevelHooksTimeout`` (~300 ms) Windows silently drops key events and may
unhook us. So this class only DECIDES on the hook thread; every command that may
touch the buffer runs on the engine's background reader.

# LOCALE KEYS TO ADD: browse.browseMode = Browse mode
# LOCALE KEYS TO ADD: browse.focusMode = Focus mode
# LOCALE KEYS TO ADD: browse.noNext = No next {0}
# LOCALE KEYS TO ADD: browse.noPrevious = No previous {0}
# LOCALE KEYS TO ADD: browse.documentStart = Start of document
# LOCALE KEYS TO ADD: browse.documentEnd = End of document
# LOCALE KEYS TO ADD: browse.emptyLine = Empty line
# LOCALE KEYS TO ADD: browse.webPage = web page
# LOCALE KEYS TO ADD: browse.scanOn = Scan mode on, {0} elements
# LOCALE KEYS TO ADD: browse.scanOff = Scan mode off
# LOCALE KEYS TO ADD: browse.scanEmpty = Nothing to scan in this window
# LOCALE KEYS TO ADD: browse.scanReading = Reading the screen
# LOCALE KEYS TO ADD: browse.refreshed = Refreshed, {0} elements
# LOCALE KEYS TO ADD: browse.sourceOcr = read by AI
# LOCALE KEYS TO ADD: browse.sourceLegacy = legacy application
"""

import ctypes
import os
import threading
import time
from typing import List, Optional

from titan_access.localization import L
from titan_access import localization as loc
from titan_access import quick_nav as qn
from titan_access import virtual_buffer as vbuf
from titan_access.virtual_buffer import VNode
from titan_access.contracts import (
    SND_CLICK, SND_CURSOR, SND_EDGE, SND_WINDOW,
    STATE_CHECKED, STATE_UNCHECKED, STATE_PARTIAL, STATE_SELECTED,
    STATE_UNAVAILABLE, STATE_EXPANDED, STATE_COLLAPSED,
)

_DBG = bool(os.environ.get("TITAN_ACCESS_DEBUG"))

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
# WebView2 and Electron apps whose own process name is not a browser.
_WEB_FRAMEWORKS = {"chrome", "gecko", "webview", "edge", "blink"}

# Window classes that host a rendered web document.
_WEB_WINDOW_CLASSES = {
    "chrome_renderwidgethosthwnd",   # Chromium (all variants + WebView2 / CEF)
    "mozillawindowclass",            # Firefox / Gecko
    "mozillacontentwindowclass",
}

# Minimum bounding-rectangle area (px^2) for a DocumentControl to count as a web
# *content* viewport rather than a small browser-chrome document (omnibox list,
# etc.). ~316x316; the page viewport is far larger, chrome documents far smaller.
_MIN_CONTENT_AREA = 100000

# How old a document may get before it is refreshed. A single-page app replaces
# its whole content without ever changing the document's runtime id, so age is
# the only general signal there is that the buffer may no longer describe what
# is on screen.
#
# CRITICAL: reaching this age never makes the user WAIT. The refresh runs on its
# own thread while the keystroke that noticed it navigates the buffer we already
# have (see :meth:`_ensure_document`). A rebuild costs half a second of
# cross-process calls, and a screen reader that spends half a second before
# answering an arrow key is the thing this whole change exists to remove.
_WEB_MAX_AGE = 20.0
# The same, for a scanned application (which changes far less often, and whose
# rebuild is more expensive).
_SCAN_MAX_AGE = 45.0

# How long a resolved web content document is reused before it is looked up
# again. Finding it means walking the browser's UIA tree, which must not happen
# on a keystroke; the window handle and title are what actually change when the
# user moves to another page or tab, and both are free to read.
_ROOT_CACHE_S = 8.0

# Virtual key codes.
_VK_LEFT, _VK_UP, _VK_RIGHT, _VK_DOWN = 0x25, 0x26, 0x27, 0x28
_VK_HOME, _VK_END, _VK_PRIOR, _VK_NEXT = 0x24, 0x23, 0x21, 0x22

# How many entries Page Up / Page Down moves.
_PAGE = 15

# Roles that put a web document into focus (pass-through) mode automatically,
# so typing edits the field instead of driving quick navigation (NVDA-style).
_FOCUS_MODE_ROLES = {"edit", "password", "combobox", "spinner", "slider"}

# Pitches for a node announcement, mirroring accessible.py (kept local to avoid
# importing the announcer for three integers).
_NAME_PITCH = 0
_ROLE_PITCH = -4
_STATE_PITCH = 4

_STATE_LABELS = (STATE_CHECKED, STATE_UNCHECKED, STATE_PARTIAL, STATE_SELECTED,
                 STATE_UNAVAILABLE, STATE_EXPANDED, STATE_COLLAPSED)


class BrowseModeHandler:
    """Browse mode (web) and scan mode (any application), bound to the engine.

    Construction never touches UIA; a document is built lazily, off the hook
    thread, the first time a key needs it.
    """

    def __init__(self, engine):
        self.engine = engine
        self._pass_through = False
        self._manual_override = False   # user pressed the toggle; pause auto-switch
        self._was_web = False           # were we inside a web document last focus?
        self._last_content_doc = None   # last good web content document (Control)

        # The active document.
        self._doc: Optional[vbuf.VirtualDocument] = None
        self._index = -1
        self._char_pos = 0
        self._doc_key = ()              # what the current document was built for
        self._lock = threading.RLock()

        # Scan mode (ordinary applications).
        self._scan = False
        self._scan_hwnd = 0
        self._building = False

        # A background rebuild in flight (never more than one), and the cached
        # content-document lookup it would otherwise repeat on every keystroke.
        self._rebuilding = False
        self._root_cache = None         # (hwnd, title, when, Control)
        self._last_landmark = ""        # region last announced while arrowing
        self._scrolling = False
        self._scroll_target = None

    # ==================================================================== #
    # Activation state
    # ==================================================================== #
    @property
    def is_active(self) -> bool:
        """True when document keys (arrows / quick nav) belong to us."""
        if self._scan:
            return True
        if not _UIA:
            return False
        try:
            return self._foreground_is_browser()
        except Exception:
            return False

    @property
    def is_web(self) -> bool:
        """True when focus is inside a web document (not a scanned app)."""
        if not _UIA:
            return False
        try:
            return self._foreground_is_browser()
        except Exception:
            return False

    @property
    def scan_active(self) -> bool:
        return bool(self._scan)

    @property
    def pass_through(self) -> bool:
        return self._pass_through

    @property
    def source(self) -> str:
        """Which tier built the active document ('uia', 'msaa', 'ocr', ...)."""
        return self._doc.source if self._doc is not None else ""

    def _foreground_is_browser(self) -> bool:
        pid = _foreground_pid()
        if pid and _process_name_for_pid(pid) in _BROWSER_PROCESSES:
            return True
        obj = getattr(self.engine, "current_object", None)
        if obj is not None:
            if getattr(obj, "process_id", 0) and \
                    _process_name_for_pid(obj.process_id) in _BROWSER_PROCESSES:
                return True
            fw = (getattr(obj, "framework_id", "") or "").lower()
            if fw in _WEB_FRAMEWORKS:
                return True
        # Last resort: the foreground window contains a web-render child window
        # (WebView2 / CEF content embedded in a host app or dialog).
        if _foreground_hosts_web_document():
            return True
        return False

    # ==================================================================== #
    # Mode toggles
    # ==================================================================== #
    def toggle(self):
        """What the reader modifier + Space does.

        In a web document it switches between browse and focus mode (the page is
        already a document). Anywhere else it switches SCAN mode on and off,
        turning the application's interface into that same document.
        """
        if self.is_web:
            self.toggle_pass_through()
            return True
        return self.toggle_scan()

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

    def toggle_scan(self) -> bool:
        """Turn scan mode on or off for the foreground application."""
        if self._scan:
            self._end_scan()
            return True
        if not self._scan_allowed():
            return False
        hwnd = vbuf.foreground_hwnd()
        if not hwnd:
            return False
        if self._building:
            return True
        self._building = True
        self._scan_hwnd = hwnd
        self.engine.play(SND_WINDOW)
        self._dispatch(lambda: self._start_scan(hwnd))
        return True

    def _scan_allowed(self) -> bool:
        """The user's own switch (Settings -> scan mode), default on."""
        settings = getattr(self.engine, "settings", None)
        if settings is None:
            return True
        try:
            return bool(settings.scan_mode)
        except Exception:
            return True

    def _start_scan(self, hwnd):
        """Build the document for *hwnd* and enter scan mode (reader thread)."""
        try:
            doc = self._build_document(hwnd, allow_ocr=True)
            if doc is None or not doc.nodes:
                self._scan = False
                self.engine.play(SND_EDGE)
                self.engine.speak(L("browse.scanEmpty"))
                return
            with self._lock:
                self._doc = doc
                self._index = 0
                self._char_pos = 0
                self._scan = True
                self._scan_hwnd = hwnd
                self._pass_through = False
            self.engine.play(SND_CURSOR)
            message = L("browse.scanOn", len(doc.nodes))
            extra = self._source_note(doc.source)
            self.engine.speak(f"{message}, {extra}" if extra else message)
            # Read where the cursor starts, so the mode is immediately useful.
            node = self._node_at(0)
            if node is not None:
                self._announce_node(node, move_focus=False)
        finally:
            self._building = False

    def _end_scan(self):
        with self._lock:
            self._scan = False
            self._doc = None
            self._index = -1
            self._char_pos = 0
            self._last_landmark = ""
        self.engine.play(SND_EDGE)
        self.engine.speak(L("browse.scanOff"))

    def _source_note(self, source) -> str:
        """A short word about where the document came from, when it matters."""
        if source == "ocr":
            return L("browse.sourceOcr")
        if source in ("msaa", "win32"):
            return L("browse.sourceLegacy")
        return ""

    def update_for_focus(self, obj):
        """React to a focus change.

        In a web document: auto-switch browse vs focus mode (NVDA-style) --
        editable / form controls get focus mode, other content browse mode.
        In scan mode: leave scan when the user changes application, and keep the
        document cursor on whatever the app just focused.
        """
        if self._scan:
            self._scan_follow_focus(obj)
            return
        active = self.is_web
        if _DBG:
            print(f"[TitanAccess][browse] update_for_focus role="
                  f"{getattr(obj,'role',None)!r} web={active} "
                  f"pass_through={self._pass_through} was_web={self._was_web}",
                  flush=True)
        if not _UIA or not active:
            self._manual_override = False
            self._was_web = False
            return
        if not self._was_web:
            self._was_web = True
            self._announce_web_entry(obj)
            # Warm the document off the focus thread so the first arrow key
            # finds it ready instead of paying for the whole walk.
            self._dispatch(lambda: self._ensure_document())
        want_focus = obj is not None and obj.role in _FOCUS_MODE_ROLES
        if want_focus == self._pass_through:
            self._manual_override = False
            return
        if self._manual_override:
            self._manual_override = False
            return
        self._pass_through = want_focus
        if want_focus:
            self.engine.play(SND_CLICK)
            self.engine.speak(L("browse.focusMode"))
        else:
            self.engine.play(SND_CURSOR)
            self.engine.speak(L("browse.browseMode"))

    def _scan_follow_focus(self, obj):
        """Keep scan mode honest when the user tabs or changes window."""
        hwnd = vbuf.foreground_hwnd()
        if hwnd and self._scan_hwnd and hwnd != self._scan_hwnd:
            # A different window: the document no longer describes what is in
            # front of the user, so scan mode ends rather than navigating a
            # window they left.
            self._end_scan()
            return
        if obj is None:
            return
        # Move the document cursor to whatever now has the focus, so switching
        # between Tab and the document cursor does not lose the place.
        name = (getattr(obj, "name", "") or "").strip()
        if not name:
            return
        with self._lock:
            nodes = self._doc.nodes if self._doc else []
            for i, node in enumerate(nodes):
                if node.name == name and node.role == getattr(obj, "role", ""):
                    self._index = i
                    self._char_pos = 0
                    break

    def _announce_web_entry(self, obj):
        """Announce that focus has entered a browsable web document."""
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
        """Handle a plain key in document mode. Return True to consume it."""
        if self._pass_through or (not _UIA and not self._scan):
            return False
        if alt:
            return False

        if ctrl:
            # Ctrl+Home / Ctrl+End jump to the ends of the document; Ctrl+Left /
            # Ctrl+Right move by word. Everything else with Ctrl belongs to the
            # application.
            if vk == _VK_HOME:
                self._dispatch(lambda: self._move_to_end(first=True))
                return True
            if vk == _VK_END:
                self._dispatch(lambda: self._move_to_end(first=False))
                return True
            if vk in (_VK_LEFT, _VK_RIGHT):
                delta = -1 if vk == _VK_LEFT else 1
                self._dispatch(lambda: self._move_word(delta))
                return True
            return False

        if key_name == "enter":
            self._dispatch(self._activate_current)
            return True
        if key_name == "escape" and self._scan:
            # Escape leaves scan mode, so the application is instantly usable
            # again without hunting for the toggle.
            self._end_scan()
            return True
        if key_name == "f5":
            self._dispatch(self.refresh)
            return True
        if key_name == "tab":
            # Let the application move focus; scan mode follows it (see
            # _scan_follow_focus) instead of fighting it.
            return False
        if vk == _VK_UP:
            self._dispatch(lambda: self._move_line(-1))
            return True
        if vk == _VK_DOWN:
            self._dispatch(lambda: self._move_line(+1))
            return True
        if vk == _VK_LEFT:
            self._dispatch(lambda: self._move_char(-1))
            return True
        if vk == _VK_RIGHT:
            self._dispatch(lambda: self._move_char(+1))
            return True
        if vk == _VK_HOME:
            self._dispatch(lambda: self._move_line_edge(start=True))
            return True
        if vk == _VK_END:
            self._dispatch(lambda: self._move_line_edge(start=False))
            return True
        if vk == _VK_PRIOR:
            self._dispatch(lambda: self._move_line(-_PAGE))
            return True
        if vk == _VK_NEXT:
            self._dispatch(lambda: self._move_line(+_PAGE))
            return True

        # Single-letter / digit quick navigation.
        ch = _char_for_key(vk, key_name)
        if not ch:
            return False
        qn_type = qn.type_for_key(ch)
        if qn_type == qn.QuickNavType.NONE:
            return False
        self._dispatch(lambda: self._quick_nav(qn_type, backward=shift))
        return True

    def _dispatch(self, fn):
        """Run document work off the keyboard-hook thread."""
        engine = self.engine
        submit = getattr(engine, "submit_read", None)
        if callable(submit):
            submit(fn)
            return
        threading.Thread(target=fn, daemon=True).start()

    def quick_nav_by_char(self, ch, backward=False) -> bool:
        """Public entry used by the dial: jump by the type bound to *ch*."""
        qn_type = qn.type_for_key((ch or "").lower())
        if qn_type == qn.QuickNavType.NONE:
            return False
        if not self._ensure_document():
            return False
        self._quick_nav(qn_type, backward=backward)
        return True

    # ==================================================================== #
    # Document construction
    # ==================================================================== #
    def _build_document(self, hwnd=0, allow_ocr=False):
        """Build the document for the current context (reader thread only).

        ``allow_ocr`` is off unless the user explicitly asked for this document
        (turning scan mode on, or refreshing it): reading a window with the AI
        sends a picture of it to their provider, so it must never be a side
        effect of, say, a dial gesture that happened to find no buffer.
        """
        if self._scan or not self.is_web:
            hwnd = hwnd or self._scan_hwnd or vbuf.foreground_hwnd()
            return vbuf.build_for_window(
                hwnd, allow_ocr=allow_ocr and self._ocr_allowed(),
                on_status=lambda stage: self._announce_stage(stage))
        return self._build_web_document()

    def _build_web_document(self):
        """The page's own document: UIA under the content root, else IA2."""
        hwnd = _foreground_hwnd()
        title = _foreground_window_title()
        doc = vbuf.VirtualDocument(hwnd=hwnd, title=title)
        root = self._document_root()
        nodes: List[VNode] = []
        if root is not None:
            try:
                # web=True: no grouping or landmark lines of their own, the way
                # a page reads in NVDA (the regions ride on the content).
                nodes = vbuf.build_uia(
                    root, deadline=time.time() + vbuf.BUILD_BUDGET_S, web=True)
            except Exception as e:
                print(f"[TitanAccess] browse_mode: buffer build failed: {e}")
                nodes = []
        # IA2 fallback: Chromium / Gecko keep the page in a render fragment a
        # downward UIA walk of the window never reaches, so a walk that yields
        # just the empty wrapper (<= 1 node) means "ask IA2", not "empty page".
        if len(nodes) <= 1:
            ia2_nodes = vbuf.build_ia2(hwnd)
            if len(ia2_nodes) > len(nodes):
                nodes = ia2_nodes
                doc.source = "ia2"
        if not doc.source:
            doc.source = "uia"
        doc.nodes = nodes
        doc.signature = (hwnd, title)
        doc.built_at = time.time()
        return doc

    def _ocr_allowed(self) -> bool:
        """Whether the AI may be asked to read a window that answers nothing."""
        try:
            from titan_access import ocr_assist
            return ocr_assist.available(getattr(self.engine, "settings", None))
        except Exception:
            return False

    def _announce_stage(self, stage):
        """Progress from a slow AI reading ('capturing' / 'reading')."""
        if stage in ("capturing", "reading"):
            try:
                self.engine.speak(L("browse.scanReading"), interrupt=False)
            except Exception:
                pass

    def _ensure_document(self, force=False, allow_ocr=False) -> bool:
        """Make sure a usable document exists, WITHOUT making the user wait.

        The first build of a document is synchronous - there is nothing to read
        until it finishes. Every later one is not: a buffer that has gone stale
        is refreshed on its own thread while the keystroke that noticed goes on
        navigating the buffer already in hand. This is the difference between a
        reader that answers every arrow key immediately and one that stops for
        half a second whenever it decides to re-read the page.
        """
        with self._lock:
            doc = self._doc
        if not force and doc is not None and doc.nodes:
            if self._cheap_stale(doc):
                self._schedule_rebuild(allow_ocr)
            return True
        return self._rebuild_now(allow_ocr)

    def _schedule_rebuild(self, allow_ocr=False):
        """Refresh the document in the background; never more than one at once.

        Deliberately NOT ``_dispatch``: the engine's reader thread is where the
        next arrow key will want to be read, and a build parked there would put
        the whole page walk in front of it - exactly the stall this avoids.
        """
        with self._lock:
            if self._rebuilding:
                return
            self._rebuilding = True

        def _run():
            try:
                self._rebuild_now(allow_ocr)
            except Exception as e:
                print(f"[TitanAccess] browse_mode: background refresh failed: {e}")
            finally:
                with self._lock:
                    self._rebuilding = False

        threading.Thread(target=_run, daemon=True,
                         name="TitanAccessBufferRefresh").start()

    def _rebuild_now(self, allow_ocr=False) -> bool:
        """Build the document on THIS thread and install it."""
        with self._lock:
            doc = self._doc
        # A document the AI read may only be rebuilt by the AI: the very reason
        # it exists is that the accessibility tiers answer nothing here, so a
        # rebuild without OCR would find nothing and we would keep re-walking
        # the same empty tree on every keystroke.
        if doc is not None and doc.source == "ocr":
            allow_ocr = True
        try:
            new_doc = self._build_document(allow_ocr=allow_ocr)
        except Exception as e:
            print(f"[TitanAccess] browse_mode: document build failed: {e}")
            return False
        if new_doc is None or not new_doc.nodes:
            # Nothing better is available: keep what we have, but stop treating
            # it as stale, or every later key pays for the same failed walk.
            if doc is not None and doc.nodes:
                doc.built_at = time.time()
                doc.signature = self._cheap_signature(doc)
                return True
            return False
        with self._lock:
            current = self._node_at_locked(self._index)
            self._doc = new_doc
            self._index = _same_place(new_doc.nodes, current, self._index)
            self._char_pos = 0
            # The region context belongs to the document that was replaced.
            self._last_landmark = ""
        return True

    def _node_at_locked(self, index):
        nodes = self._doc.nodes if self._doc else []
        return nodes[index] if 0 <= index < len(nodes) else None

    def _cheap_signature(self, doc):
        """"Is this still the same screen?", costing nothing.

        Checked on every navigation key, so it may only use what Windows can
        answer without leaving the process: the foreground window and its title.
        The old signature asked UI Automation for the page's document element -
        which meant resolving it (a walk of the browser's tree, sometimes a
        breadth-first search of thousands of elements) before every single arrow
        key. Whether the CONTENT changed under an unchanged title is answered by
        the age check instead, and by the refresh it schedules in the background.
        """
        if self._scan:
            return vbuf.signature_for(doc.hwnd, doc)
        hwnd = _foreground_hwnd()
        return (hwnd, vbuf.window_text(hwnd))

    def _cheap_stale(self, doc) -> bool:
        if self._scan:
            return vbuf.looks_stale(doc, max_age=_SCAN_MAX_AGE)
        if (time.time() - doc.built_at) > _WEB_MAX_AGE:
            return True
        return self._cheap_signature(doc) != doc.signature

    def refresh(self):
        """Rebuild the document now (F5) and say how big it is."""
        if not self._ensure_document(force=True, allow_ocr=bool(self._scan)):
            self.engine.play(SND_EDGE)
            self.engine.speak(L("browse.scanEmpty"))
            return False
        with self._lock:
            count = len(self._doc.nodes) if self._doc else 0
        self.engine.play(SND_CURSOR)
        self.engine.speak(L("browse.refreshed", count))
        return True

    # -- the web content document ---------------------------------------- #
    def _document_root(self):
        """Locate the **web content** document of the foreground browser window.

        The browser chrome (address bar, toolbars, menus) is itself web UI in
        modern Chromium/Edge, so several ``DocumentControl`` elements exist. We
        must return the *content* document, or browse mode reads the browser
        menu instead of the page.

        The answer is cached against the window and its title: resolving it
        walks the browser's UIA tree (and, when focus is on the chrome, searches
        it breadth-first), which is far too expensive to repeat for a keystroke.
        A different window, a different page or a new tab all change one of
        those two, and the lookup happens again.
        """
        if not _UIA:
            return None
        hwnd = _foreground_hwnd()
        title = vbuf.window_text(hwnd)
        cached = self._root_cache
        if (cached is not None and cached[0] == hwnd and cached[1] == title
                and (time.time() - cached[2]) < _ROOT_CACHE_S
                and self._is_content_document(cached[3])):
            return cached[3]
        root = self._resolve_document_root()
        self._root_cache = (hwnd, title, time.time(), root)
        return root

    def _resolve_document_root(self):
        try:
            hwnd = _foreground_hwnd()
            window = auto.ControlFromHandle(hwnd) if hwnd else auto.GetForegroundControl()
        except Exception:
            window = None
        try:
            focused = auto.GetFocusedControl()
        except Exception:
            focused = None
        doc = self._nearest_document(focused) if focused is not None else None
        if self._is_content_document(doc):
            self._last_content_doc = doc
            return doc
        if window is not None:
            main = self._find_main_document(window)
            if self._is_content_document(main):
                self._last_content_doc = main
                return main
        # Focus is on the browser chrome: reuse the last content document if it
        # is still alive. NEVER fall back to the chrome window itself.
        last = getattr(self, "_last_content_doc", None)
        if last is not None and self._is_content_document(last):
            return last
        self._last_content_doc = None
        return None

    @staticmethod
    def _is_content_document(doc) -> bool:
        if doc is None:
            return False
        try:
            if _ctype(doc) != "DocumentControl":
                return False
            fw = (doc.FrameworkId or "").lower()
            if fw and fw not in _WEB_FRAMEWORKS:
                return False
            return _control_area(doc) >= _MIN_CONTENT_AREA
        except Exception:
            return False

    def _find_main_document(self, window):
        """Bounded BFS for the largest web ``DocumentControl`` under *window*."""
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

    # ==================================================================== #
    # Navigation
    # ==================================================================== #
    def _nodes(self):
        with self._lock:
            return self._doc.nodes if self._doc else []

    def _node_at(self, index):
        nodes = self._nodes()
        if 0 <= index < len(nodes):
            return nodes[index]
        return None

    def _move_line(self, delta) -> bool:
        if not self._ensure_document():
            return False
        nodes = self._nodes()
        with self._lock:
            new = self._index + delta
        if new < 0:
            if self._index <= 0:
                self.engine.play(SND_EDGE)
                self.engine.speak(L("browse.documentStart"))
                return True
            new = 0
        if new >= len(nodes):
            if self._index >= len(nodes) - 1:
                self.engine.play(SND_EDGE)
                self.engine.speak(L("browse.documentEnd"))
                return True
            new = len(nodes) - 1
        with self._lock:
            self._index = new
            self._char_pos = 0
        self._announce_node(nodes[new])
        return True

    def _move_to_end(self, first=True) -> bool:
        if not self._ensure_document():
            return False
        nodes = self._nodes()
        if not nodes:
            return False
        index = 0 if first else len(nodes) - 1
        with self._lock:
            self._index = index
            self._char_pos = 0
        self.engine.speak(L("browse.documentStart" if first else "browse.documentEnd"),
                          interrupt=True)
        self._announce_node(nodes[index])
        return True

    def _move_line_edge(self, start=True) -> bool:
        """Home / End: the first or last character of the current entry."""
        if not self._ensure_document():
            return False
        node = self._node_at(self._index)
        if node is None:
            return False
        text = node.text
        with self._lock:
            self._char_pos = 0 if start or not text else len(text) - 1
        if not text:
            self.engine.speak(L("browse.emptyLine"))
            return True
        self.engine.speak(loc.character_announcement(text[self._char_pos],
                                                     use_phonetic=False))
        return True

    def _move_char(self, delta) -> bool:
        if not self._ensure_document():
            return False
        node = self._node_at(self._index)
        if node is None:
            return False
        text = node.text
        if not text:
            self.engine.speak(L("browse.emptyLine"))
            return True
        new = self._char_pos + delta
        if new < 0 or new >= len(text):
            self.engine.play(SND_EDGE)
            self.engine.speak(L("browse.documentStart") if delta < 0
                              else L("browse.documentEnd"))
            return True
        with self._lock:
            self._char_pos = new
        self.engine.speak(loc.character_announcement(text[new], use_phonetic=False))
        return True

    def _move_word(self, delta) -> bool:
        """Ctrl+Left / Ctrl+Right: by word within the current entry."""
        if not self._ensure_document():
            return False
        node = self._node_at(self._index)
        if node is None:
            return False
        text = node.text
        if not text:
            self.engine.speak(L("browse.emptyLine"))
            return True
        starts = _word_starts(text)
        if not starts:
            return True
        position = self._char_pos
        if delta > 0:
            nxt = next((s for s in starts if s > position), None)
        else:
            nxt = next((s for s in reversed(starts) if s < position), None)
        if nxt is None:
            self.engine.play(SND_EDGE)
            self.engine.speak(L("browse.documentStart") if delta < 0
                              else L("browse.documentEnd"))
            return True
        with self._lock:
            self._char_pos = nxt
        end = next((s for s in starts if s > nxt), len(text))
        self.engine.speak(text[nxt:end].strip() or text[nxt])
        return True

    def _quick_nav(self, qn_type, backward):
        if not self._ensure_document():
            self.engine.play(SND_EDGE)
            self.engine.speak(L("browse.scanEmpty"))
            return
        nodes = self._nodes()
        start = self._index if self._index >= 0 else 0
        rng = (range(start - 1, -1, -1) if backward
               else range(start + 1, len(nodes)))
        for i in rng:
            if self._matches(nodes[i], qn_type):
                with self._lock:
                    self._index = i
                    self._char_pos = 0
                self._announce_node(nodes[i], qn_type)
                return
        label = qn.type_label(qn_type)
        self.engine.play(SND_EDGE)
        self.engine.speak(L("browse.noPrevious", label) if backward
                          else L("browse.noNext", label))

    @staticmethod
    def _matches(node: VNode, qn_type) -> bool:
        """Does *node* satisfy a quick-navigation type?

        Matched on the Titan role key, so it works identically whether the
        document came from UI Automation, MSAA, the raw child windows or the
        AI's reading of a picture.
        """
        if qn.is_heading(qn_type):
            if not node.is_heading:
                return False
            want = qn.heading_level(qn_type)
            return want == 0 or node.level == want
        if qn_type == qn.QuickNavType.LANDMARK:
            # A landmark is not a line of the document any more (NVDA does not
            # make it one either), so d / n look for the first entry INSIDE each
            # region rather than for a "group" entry standing before it. A
            # document with no regions at all still falls back to the container
            # roles below, which is what an application scanned in scan mode has.
            if getattr(node, "landmark_start", False):
                return True
            if getattr(node, "landmark", ""):
                return False
        roles = qn.roles_for(qn_type)
        if not roles:
            return False
        if node.role in roles:
            if qn_type == qn.QuickNavType.PARAGRAPH and not node.name:
                return False
            return True
        return False

    # ==================================================================== #
    # Activation + say all
    # ==================================================================== #
    def _activate_current(self) -> bool:
        """Press whatever the document cursor is on (Enter)."""
        node = self._node_at(self._index)
        if node is None:
            return False
        ok = vbuf.activate(node)
        self.engine.play(SND_CLICK if ok else SND_EDGE)
        if ok and self._scan:
            # Pressing something usually changes the window, so the document
            # that described it is no longer true.
            self._dispatch(lambda: self._after_activation())
        return True

    def _after_activation(self):
        time.sleep(0.4)
        self._ensure_document(force=True)

    def say_all(self) -> bool:
        """Read continuously from the cursor to the end of the document.

        Every line is QUEUED rather than spoken over the last one: the speech
        adapter owns a real queue, so this reads the document at the speed of
        the voice instead of racing it (and a keypress interrupts, as always).
        """
        if not self._ensure_document():
            return False

        def _run():
            nodes = self._nodes()
            speech = getattr(self.engine, "speech", None)
            start = self._index if self._index >= 0 else 0
            for j in range(start, len(nodes)):
                text = nodes[j].text
                if not text:
                    continue
                with self._lock:
                    self._index = j
                self.engine.speak(text, interrupt=(j == start))
                if speech is not None and hasattr(speech, "pending_count"):
                    # Keep at most a couple of lines queued ahead, so the voice
                    # never runs dry between lines and an interrupt is instant.
                    while speech.pending_count() > 2:
                        time.sleep(0.05)
                        if not self.is_active:
                            return
                else:
                    time.sleep(min(2.5, 0.28 + len(text) / 16.0))

        threading.Thread(target=_run, daemon=True).start()
        return True

    # ==================================================================== #
    # Announcement
    # ==================================================================== #
    def _announce_node(self, node: VNode, qn_type=None, move_focus=True):
        """Read one document entry.

        In a web document this is deliberately all local. The buffer was built
        with every property already cached, so an arrow key costs no
        cross-process call at all; handing the node back to the full announcer
        (which re-reads the live element through the provider) is what made
        arrowing a page feel heavy. It also moved the real keyboard focus onto
        every entry the cursor passed - which NVDA does not do in browse mode,
        because it scrolls the page under the user, fires focus events straight
        back at the reader, and in a form starts typing into a field they only
        went past. The page is scrolled instead, behind the announcement.

        In scan mode the document is an application's own controls, it is small,
        and its focus IS the useful cursor - so there the live announcer and the
        real focus move are kept.
        """
        if self._scan:
            if move_focus:
                try:
                    vbuf.focus_node(node)
                except Exception:
                    pass
            if node.source == "uia":
                control = vbuf.uia_control(node)
                ao = self._to_accessible(control) if control is not None else None
                if ao is not None:
                    try:
                        self.engine.announce_object(ao, for_navigation=True)
                        return
                    except Exception:
                        pass
        else:
            self._scroll_later(node)
        self.engine.play(SND_CURSOR)
        self.engine.speak_segments(self._segments_for(node, qn_type))

    def _scroll_later(self, node):
        """Bring the entry on screen off the announcement's critical path."""
        with self._lock:
            self._scroll_target = node
            if self._scrolling:
                return
            self._scrolling = True

        def _run():
            try:
                while True:
                    with self._lock:
                        target = self._scroll_target
                        self._scroll_target = None
                        if target is None:
                            self._scrolling = False
                            return
                    try:
                        vbuf.scroll_into_view(target)
                    except Exception:
                        pass
            except Exception:
                with self._lock:
                    self._scrolling = False

        threading.Thread(target=_run, daemon=True,
                         name="TitanAccessScroll").start()

    def _segments_for(self, node: VNode, qn_type=None):
        """(text, pitch) parts for a node, read straight out of the buffer."""
        segments = []
        # The region the entry sits in, announced when the cursor crosses into
        # it - NVDA's behaviour, and the reason a page has no "navigation,
        # group" line standing in front of its navigation.
        landmark = self._landmark_segment(node)
        if landmark:
            segments.append(landmark)
        name = node.name or node.value
        if name:
            segments.append((name, _NAME_PITCH))
        if node.is_heading:
            level = node.level or (qn.heading_level(qn_type) if qn_type else 0)
            segments.append((L("quickNav.headingLevel", level) if level
                             else L("quickNav.heading"), _ROLE_PITCH))
        elif node.role and node.role not in ("text", "unknown"):
            segments.append((loc.role_label(node.role), _ROLE_PITCH))
        if node.value and node.value != node.name:
            segments.append((node.value, _NAME_PITCH))
        for state in node.states:
            if state in _STATE_LABELS:
                segments.append((loc.state_label(state), _STATE_PITCH))
        if node.size_of_set and node.pos_in_set and self._want_position():
            segments.append((L("element.positionOf", node.pos_in_set,
                               node.size_of_set), _NAME_PITCH))
        if not segments:
            segments = [(L("browse.emptyLine"), _NAME_PITCH)]
        return segments

    def _want_position(self) -> bool:
        """The same verbosity switch the focus announcer honours ("3 of 10")."""
        settings = getattr(self.engine, "settings", None)
        if settings is None:
            return True
        try:
            return settings.get_bool("Verbosity", "AnnounceListPosition", True)
        except Exception:
            return True

    def _landmark_segment(self, node):
        """"main landmark" the first time the cursor enters that region."""
        landmark = getattr(node, "landmark", "")
        if landmark == self._last_landmark:
            return None
        self._last_landmark = landmark
        if not landmark:
            return None
        return (f"{landmark}, {qn.type_label(qn.QuickNavType.LANDMARK)}",
                _ROLE_PITCH)

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
    return vbuf.window_text(_foreground_hwnd())


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
    """True when the foreground window contains a web-render child window."""
    global _web_doc_cache
    try:
        hwnd = _foreground_hwnd()
    except Exception:
        return False
    if not hwnd:
        return False
    cached_hwnd, cached_at, cached_val = _web_doc_cache
    now = time.time()
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


def _control_area(control) -> int:
    """Bounding-rectangle area of *control* in px^2 (0 when unavailable)."""
    try:
        r = control.BoundingRectangle
        wdt = max(0, int(getattr(r, "right", 0)) - int(getattr(r, "left", 0)))
        hgt = max(0, int(getattr(r, "bottom", 0)) - int(getattr(r, "top", 0)))
        return wdt * hgt
    except Exception:
        return 0


def _same_place(nodes, previous, fallback_index) -> int:
    """Where the cursor should land in a freshly built document.

    A refresh must not throw the user back to the top of the page, and it must
    not silently move them either: the entry they were on is looked for by what
    it says and what it is, nearest to where it used to be, before falling back
    to the same ordinal position.
    """
    if not nodes:
        return 0
    if previous is not None and (previous.name or previous.value):
        key = (previous.name, previous.role, previous.value)
        best = None
        for i, node in enumerate(nodes):
            if (node.name, node.role, node.value) == key:
                if best is None or abs(i - fallback_index) < abs(best - fallback_index):
                    best = i
        if best is not None:
            return best
    if fallback_index < 0:
        return 0
    return min(fallback_index, len(nodes) - 1)


def _word_starts(text) -> list:
    """Index of the first character of every word in *text*."""
    starts = []
    previous_blank = True
    for i, ch in enumerate(text):
        blank = ch.isspace()
        if previous_blank and not blank:
            starts.append(i)
        previous_blank = blank
    return starts


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
