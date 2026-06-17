# -*- coding: utf-8 -*-
"""
Titan Buffer System - core data model.

An audio-game-style buffer review system shared by the Titan GUI, Klango mode
and the tilde-activated Titan UI overlay. A single, process-wide buffer state
is navigated with three pairs of keys (category / buffer / element), so review
behaves identically no matter which interface the user is in.

Hierarchy:
    Category (e.g. "Titan", "Titan-Net", "Elten", "Telegram")
      -> Buffer (e.g. "Chat", "Private messages", "Notifications", "All")
           -> Element (one message / notification)

The special virtual "All" buffer merges every real buffer in its category,
sorted by timestamp. It is computed on demand and only exposed when a category
has two or more real buffers.

Storage is session-only (in-memory); nothing is persisted to disk.
"""

import time
import threading
from collections import OrderedDict, deque

# Maximum number of elements kept per real buffer (oldest are evicted).
DEFAULT_MAX_ELEMENTS = 500

# Reserved id/name of the virtual merged buffer.
ALL_BUFFER_ID = "__all__"


class BufferElement:
    """A single reviewable item (a chat line, PM, notification, ...)."""

    __slots__ = ("text", "author", "kind", "timestamp", "raw")

    def __init__(self, text, author=None, kind=None, timestamp=None, raw=None):
        self.text = str(text) if text is not None else ""
        self.author = author          # display name of sender, or None
        self.kind = kind              # source type hint, e.g. "message" / "notification"
        self.timestamp = timestamp if timestamp is not None else time.time()
        self.raw = raw                # optional opaque payload for consumers


class Buffer:
    """An ordered, bounded list of elements with its own review cursor."""

    def __init__(self, buffer_id, name, kind=None, maxlen=DEFAULT_MAX_ELEMENTS):
        self.id = buffer_id
        self.name = name
        self.kind = kind
        self.elements = deque(maxlen=maxlen)
        self.cursor = 0               # index of the currently reviewed element


class Category:
    """A named group of buffers (one messaging backend / source domain)."""

    def __init__(self, category_id, name):
        self.id = category_id
        self.name = name
        self.buffers = OrderedDict()  # buffer_id -> Buffer (real buffers only)
        self.current_buffer_id = None
        self._all_cursor = 0          # review cursor for the virtual "All" buffer
        # An optional live handler turns this into an INTERACTIVE category
        # (e.g. the current TTS engine): its "buffers" are parameters and
        # element navigation adjusts the parameter value instead of reviewing
        # a list. See buffer_system docstring and tts_buffer.TTSParameterHandler.
        self.handler = None


# A lightweight, host-agnostic result handed to the announcer.
class NavResult:
    """Outcome of a navigation action, consumed by the announcer."""

    __slots__ = ("level", "moved", "at_boundary", "name", "index", "count",
                 "author", "text", "kind")

    def __init__(self, level, moved, at_boundary, name="", index=0, count=0,
                 author=None, text="", kind=None):
        self.level = level            # "category" | "buffer" | "element"
        self.moved = moved            # True if the cursor actually changed
        self.at_boundary = at_boundary  # True if we were already at first/last edge
        self.name = name              # category / buffer name (for those levels)
        self.index = index            # 1-based position
        self.count = count            # total at this level
        self.author = author          # element author (element level)
        self.text = text              # element text (element level)
        self.kind = kind              # source kind hint


def _clamp(value, low, high):
    return max(low, min(high, value))


class BufferManager:
    """Process-wide singleton holding all categories, buffers and cursors."""

    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._lock = threading.RLock()
        self.categories = OrderedDict()   # category_id -> Category
        self.current_category_id = None

    # ------------------------------------------------------------------ #
    #  Registration / ingestion
    # ------------------------------------------------------------------ #
    def register_category(self, category_id, name):
        """Create a category if it does not exist; return it. Idempotent.

        Safe to call from any producer (titan-net, IM modules, components,
        external modules). The first registered category becomes current.
        """
        with self._lock:
            cat = self.categories.get(category_id)
            if cat is None:
                cat = Category(category_id, name)
                self.categories[category_id] = cat
                if self.current_category_id is None:
                    self.current_category_id = category_id
            elif name:
                cat.name = name
            return cat

    def remove_category(self, category_id):
        """Remove a category (e.g. on logout/disconnect). Idempotent.

        If it was the current category, the cursor falls back to the first
        remaining category so navigation stays valid.
        """
        with self._lock:
            if category_id in self.categories:
                del self.categories[category_id]
                if self.current_category_id == category_id:
                    ids = self._category_ids()
                    self.current_category_id = ids[0] if ids else None

    def register_live_category(self, category_id, name, handler):
        """Create/replace an interactive category backed by a live `handler`.

        The handler drives its own parameter list and value changes; element
        pushes/pings never apply to it. `handler` must implement:
            list_params() -> list[(param_id, "Label: value")]
            adjust(param_id, direction, extreme=False) -> new value text
        Returns the category.
        """
        with self._lock:
            cat = self.register_category(category_id, name)
            cat.handler = handler
            try:
                params = handler.list_params()
                if params and cat.current_buffer_id is None:
                    cat.current_buffer_id = params[0][0]
            except Exception as e:
                print(f"[BufferSystem] live category init error: {e}")
            return cat

    def ensure_buffer(self, category_id, buffer_id, name, kind=None):
        """Create a buffer inside a category if missing; return it. Idempotent."""
        with self._lock:
            cat = self.categories.get(category_id)
            if cat is None:
                cat = self.register_category(category_id, category_id)
            buf = cat.buffers.get(buffer_id)
            if buf is None:
                buf = Buffer(buffer_id, name, kind=kind)
                cat.buffers[buffer_id] = buf
                if cat.current_buffer_id is None:
                    cat.current_buffer_id = buffer_id
            elif name:
                buf.name = name
                if kind:
                    buf.kind = kind
            return buf

    def add_element(self, category_id, buffer_id, text, author=None,
                    kind=None, raw=None, timestamp=None):
        """Append an element to (category, buffer), creating both if needed.

        Returns True if the element landed in the user's currently active
        category AND active buffer (so a ping should be played), else False.
        Category/buffer names default to their ids when auto-created; callers
        that want nice names should register/ensure them first.
        """
        with self._lock:
            cat = self.categories.get(category_id)
            if cat is None:
                cat = self.register_category(category_id, category_id)
            buf = cat.buffers.get(buffer_id)
            if buf is None:
                buf = self.ensure_buffer(category_id, buffer_id, buffer_id, kind=kind)

            element = BufferElement(text, author=author,
                                    kind=kind or buf.kind,
                                    timestamp=timestamp, raw=raw)
            buf.elements.append(element)
            return self.is_active_target(category_id, buffer_id)

    # ------------------------------------------------------------------ #
    #  Active-target test (used for the ping decision)
    # ------------------------------------------------------------------ #
    def is_active_target(self, category_id, buffer_id):
        """True if (category, buffer) is what the user is currently reviewing.

        Also true when the active buffer is that category's virtual "All",
        since a new element shows up there too.
        """
        with self._lock:
            if self.current_category_id != category_id:
                return False
            cat = self.categories.get(category_id)
            if cat is None:
                return False
            return cat.current_buffer_id in (buffer_id, ALL_BUFFER_ID)

    def current_element_preview(self):
        """Formatted current element (at the review cursor) of the current
        category's active buffer ("author: text" or "text"), or "" if none.
        Moves no cursor.

        Used to honour the existing `announce_first_item` IUI setting when a
        buffer category or buffer is announced. On a buffer not yet reviewed
        the cursor is 0, so this is the first element; after navigation it is
        wherever the user left off.
        """
        with self._lock:
            cat = self.categories.get(self.current_category_id)
            if cat is None or cat.current_buffer_id is None:
                return ""
            if cat.handler:
                return ""  # interactive category has no reviewable elements
            elements, get_cursor, _set = self._active_elements(cat)
            if not elements:
                return ""
            el = elements[_clamp(get_cursor(), 0, len(elements) - 1)]
            return f"{el.author}: {el.text}" if el.author else el.text

    # ------------------------------------------------------------------ #
    #  Structure helpers
    # ------------------------------------------------------------------ #
    def _category_ids(self):
        return list(self.categories.keys())

    def _buffer_list(self, cat):
        """Ordered (buffer_id, name) for a category, incl. virtual "All".

        "All" is appended only when the category has two or more real
        buffers, so a single-buffer category reads "1 of 1". For an
        interactive category the list comes from its handler (parameters).
        """
        if cat.handler:
            try:
                return list(cat.handler.list_params())
            except Exception as e:
                print(f"[BufferSystem] handler list_params error: {e}")
                return []
        ids = [(bid, b.name) for bid, b in cat.buffers.items()]
        if len(cat.buffers) >= 2:
            ids.append((ALL_BUFFER_ID, _all_buffer_name()))
        return ids

    def _all_elements(self, cat):
        """Merged, timestamp-sorted snapshot of every real buffer's elements."""
        merged = []
        for b in cat.buffers.values():
            merged.extend(b.elements)
        merged.sort(key=lambda e: e.timestamp)
        return merged

    def _active_elements(self, cat):
        """(elements_list, cursor_getter, cursor_setter) for the active buffer."""
        if cat.current_buffer_id == ALL_BUFFER_ID:
            elements = self._all_elements(cat)

            def get_cursor():
                return cat._all_cursor

            def set_cursor(v):
                cat._all_cursor = v

            return elements, get_cursor, set_cursor

        buf = cat.buffers.get(cat.current_buffer_id)
        if buf is None:
            return [], (lambda: 0), (lambda v: None)
        return list(buf.elements), (lambda: buf.cursor), \
            (lambda v: setattr(buf, "cursor", v))

    # ------------------------------------------------------------------ #
    #  Category navigation  ( -  =  and Shift _  + )
    # ------------------------------------------------------------------ #
    def _move_category(self, target_index_fn):
        with self._lock:
            ids = self._category_ids()
            if not ids:
                return NavResult("category", False, True)
            try:
                cur = ids.index(self.current_category_id)
            except ValueError:
                cur = 0
            new = _clamp(target_index_fn(cur, len(ids)), 0, len(ids) - 1)
            moved = new != cur
            self.current_category_id = ids[new]
            cat = self.categories[ids[new]]
            return NavResult("category", moved, not moved,
                             name=cat.name, index=new + 1, count=len(ids))

    def next_category(self):
        return self._move_category(lambda cur, n: cur + 1)

    def prev_category(self):
        return self._move_category(lambda cur, n: cur - 1)

    def first_category(self):
        return self._move_category(lambda cur, n: 0)

    def last_category(self):
        return self._move_category(lambda cur, n: n - 1)

    # ------------------------------------------------------------------ #
    #  Buffer navigation  ( [  ]  and Shift {  } )
    # ------------------------------------------------------------------ #
    def _move_buffer(self, target_index_fn):
        with self._lock:
            cat = self.categories.get(self.current_category_id)
            if cat is None:
                return NavResult("buffer", False, True)
            blist = self._buffer_list(cat)
            if not blist:
                return NavResult("buffer", False, True)
            ids = [bid for bid, _name in blist]
            try:
                cur = ids.index(cat.current_buffer_id)
            except ValueError:
                cur = 0
            new = _clamp(target_index_fn(cur, len(ids)), 0, len(ids) - 1)
            moved = new != cur
            cat.current_buffer_id = ids[new]
            level = "parameter" if cat.handler else "buffer"
            return NavResult(level, moved, not moved,
                             name=blist[new][1], index=new + 1, count=len(ids))

    def next_buffer(self):
        return self._move_buffer(lambda cur, n: cur + 1)

    def prev_buffer(self):
        return self._move_buffer(lambda cur, n: cur - 1)

    def first_buffer(self):
        return self._move_buffer(lambda cur, n: 0)

    def last_buffer(self):
        return self._move_buffer(lambda cur, n: n - 1)

    # ------------------------------------------------------------------ #
    #  Element navigation  ( ,  .  and Shift <  > )
    # ------------------------------------------------------------------ #
    def _adjust_value(self, cat, kind):
        """Interactive categories: adjust the current parameter's value."""
        param = cat.current_buffer_id
        direction = +1 if kind in ('next', 'last') else -1
        extreme = kind in ('first', 'last')
        try:
            value = cat.handler.adjust(param, direction, extreme=extreme)
        except Exception as e:
            print(f"[BufferSystem] handler adjust error: {e}")
            value = ""
        return NavResult("value", True, False, text=value if value is not None else "")

    def _move_element(self, kind, target_index_fn):
        with self._lock:
            cat = self.categories.get(self.current_category_id)
            if cat is None or cat.current_buffer_id is None:
                return NavResult("element", False, True, count=0)
            if cat.handler:
                return self._adjust_value(cat, kind)
            elements, get_cursor, set_cursor = self._active_elements(cat)
            n = len(elements)
            if n == 0:
                return NavResult("element", False, True, count=0)
            cur = _clamp(get_cursor(), 0, n - 1)
            new = _clamp(target_index_fn(cur, n), 0, n - 1)
            moved = new != cur
            set_cursor(new)
            el = elements[new]
            return NavResult("element", moved, not moved,
                             index=new + 1, count=n,
                             author=el.author, text=el.text, kind=el.kind)

    def next_element(self):
        return self._move_element('next', lambda cur, n: cur + 1)

    def prev_element(self):
        return self._move_element('prev', lambda cur, n: cur - 1)

    def first_element(self):
        return self._move_element('first', lambda cur, n: 0)

    def last_element(self):
        return self._move_element('last', lambda cur, n: n - 1)


# Resolved lazily so the translation system is initialised first.
def _all_buffer_name():
    try:
        from src.titan_core.translation import set_language
        from src.settings.settings import get_setting
        _ = set_language(get_setting('language', 'pl'))
        return _("All")
    except Exception:
        return "All"


def get_buffer_manager():
    """Return the process-wide BufferManager singleton (thread-safe)."""
    if BufferManager._instance is None:
        with BufferManager._instance_lock:
            if BufferManager._instance is None:
                BufferManager._instance = BufferManager()
    return BufferManager._instance
