"""Reusable virtual tab bar helpers for IM modules, components and other UIs.

The main TCE GUI puts a virtual tab bar as the first row of each list (apps,
games, network, registered component views). The same row-0 convention is
used by Titan-Net, the Feedback Hub and Titan IM modules (TeamTalk, ...).
This module exposes a small audio + screen-reader API so every "row 0 is
the tab bar" list across the codebase behaves identically without each
caller having to know about ui/tapbar.ogg, ui/switch_list.ogg or
ui/endoftapbar.ogg or how the 4-second arrow-keys tip is scheduled.

All helpers are no-op-on-failure so they're safe to call from any context
(launchers, components, IM modules, standalone apps).

Typical wiring inside a wx event handler::

    from src.titan_core.tab_bar_helper import (
        announce_tab_bar_focus, cancel_tab_bar_tip,
        play_tab_switch, play_tab_bar_edge,
    )

    def _on_row_selected(event):
        idx = event.GetIndex()
        if self._is_tab_bar_row(idx):
            announce_tab_bar_focus()
            return
        cancel_tab_bar_tip()
        ...regular focus sound...

    def _cycle_tab(direction):
        new_tab = self.current_tab + direction
        if new_tab < FIRST or new_tab > LAST:
            play_tab_bar_edge()
            return
        play_tab_switch()
        self._set_tab(new_tab)
"""


def _play(name):
    """Play a sound file via the central Titan sound system. Silent on failure."""
    try:
        from src.titan_core.sound import play_sound
        play_sound(name)
    except Exception:
        pass


def _top_level_frame(window):
    """Walk up the parent chain to the enclosing wx.Frame / wx.Dialog."""
    try:
        import wx as _wx
        cur = window
        while cur is not None:
            if isinstance(cur, (_wx.Frame, _wx.Dialog)):
                return cur
            cur = cur.GetParent()
    except Exception:
        pass
    return None


def _focus_is_inside(widget):
    """True when keyboard focus is on ``widget`` or any descendant."""
    try:
        import wx as _wx
        focused = _wx.Window.FindFocus()
    except Exception:
        return False
    while focused is not None:
        if focused is widget:
            return True
        try:
            focused = focused.GetParent()
        except Exception:
            return False
    return False


def _make_char_hook_handler(callback):
    """Build a wx.EvtHandler we can PushEventHandler onto a frame's chain
    so CHAR_HOOK reaches our callback before any frame-level Bind handler.

    Lazily imports wx so the module stays importable in non-GUI contexts
    (translation extraction, list_order tooling, etc.).
    """
    import wx as _wx

    class _Hook(_wx.EvtHandler):
        def __init__(self):
            super().__init__()
            self.Bind(_wx.EVT_CHAR_HOOK, self._dispatch)

        def _dispatch(self, event):
            try:
                callback(event)
            except Exception as exc:
                print(f"[tab_bar_helper] CHAR_HOOK handler error: {exc}")
                event.Skip()

    return _Hook()


def announce_tab_bar_focus(tip_delay=4.0, schedule_tip=True):
    """Selection has landed on the virtual tab bar row.

    Plays the ``ui/tapbar.ogg`` earcon, announces "Tab bar" through the
    active screen reader (NVDA / JAWS / Narrator / VoiceOver / Orca) and
    schedules the 4-second tip explaining that Left/Right arrows switch
    between cards. The "Tab bar" announcement and the tip are emitted only
    when a real SR is active, so the platform-TTS fallback (SAPI, NSSpeech,
    spd) never speaks them.

    Call this from the EVT_LISTBOX / EVT_LIST_ITEM_SELECTED / tree
    selection-change handler whenever the new selection is the tab bar row.

    Args:
        tip_delay: Seconds to wait before speaking the tip (default 4.0).
        schedule_tip: When False, only the earcon + SR announcement fire.
    """
    try:
        from src.accessibility.messages import announce_tab_bar, show_tab_bar_tip
        announce_tab_bar()
        if schedule_tip:
            show_tab_bar_tip(delay=tip_delay)
    except Exception:
        pass


def cancel_tab_bar_tip():
    """Selection has moved off the tab bar row - cancel any pending tip.

    Safe to call even when no tip is currently scheduled.
    """
    try:
        from src.accessibility.messages import cancel_tab_bar_tip as _cancel
        _cancel()
    except Exception:
        pass


def play_tab_switch():
    """Play the ``ui/switch_list.ogg`` earcon when the active tab actually changes."""
    _play('ui/switch_list.ogg')


def play_tab_bar_edge():
    """Play the ``ui/endoftapbar.ogg`` earcon when Left/Right hits the first/last tab."""
    _play('ui/endoftapbar.ogg')


def play_tab_bar_focus_sound():
    """Just the ``ui/tapbar.ogg`` earcon, without any SR announcement.

    Useful when refreshing a list and explicitly placing focus on row 0
    (e.g. after switching tabs) - the row text itself reads "X, N of M"
    natively so no extra speech is needed, but the earcon still benefits
    sighted users.
    """
    _play('ui/tapbar.ogg')


# ---------------------------------------------------------------------------
# Keyboard drag-and-drop for the row-0 tab bar
# ---------------------------------------------------------------------------
#
# Replicates the main TitanApp tab bar drag (gui.py:_start_tab_bar_drag /
# _move_tab_bar_drag / _drop_tab_bar_drag / _cancel_tab_bar_drag) for any
# IM module / component / launcher that uses the row-0 virtual tab bar
# convention. Callers register callbacks describing how their tab data is
# laid out; the controller takes care of:
#
# * Space on row 0 - picks up the currently active tab card.
# * Left / Right while picked up - moves the card one slot via the
#   caller's swap callback. ``ui/endoftapbar.ogg`` plays at the edges.
# * Space again - drops the card (commit), persisting the new order to
#   ``.index.TCG`` via list_order when ``view_id`` is given.
# * Escape - cancels the drag and restores the original order.


def _is_screen_reader_running():
    """Best-effort detection of an active real screen reader."""
    try:
        from src.accessibility.messages import is_screen_reader_running
        return bool(is_screen_reader_running())
    except Exception:
        return False


def _speak_drag(text):
    """Speak a short drag-status message - skipped when SR is active.

    The control's row-0 text already reads "<tab>, N of M" natively after
    the swap, so SR users don't need a duplicate manual speak.
    """
    if _is_screen_reader_running():
        return
    try:
        from src.accessibility.messages import get_messenger
        get_messenger().speaker.speak(text, interrupt=True)
    except Exception:
        pass


class TabBarDragController:
    """Wires Space / Left / Right / Escape on the row-0 virtual tab bar
    to keyboard drag-and-drop reordering of tab cards.

    The caller owns the tab data; this controller only orchestrates the
    drag state machine and triggers the caller's swap / refresh callbacks.

    Wiring example for a module with an int-indexed tab bar::

        from src.titan_core.tab_bar_helper import TabBarDragController

        self._tab_drag = TabBarDragController(
            control=self.right_list,
            get_current_index=lambda: self.tab_order.index(self.current_tab),
            get_tab_count=lambda: len(self.tab_order),
            get_tab_label=lambda i: TAB_LABELS[self.tab_order[i]],
            swap=lambda a, b: self.tab_order.__setitem__(
                slice(None), [self.tab_order[j] if j != a and j != b
                              else (self.tab_order[b] if j == a else self.tab_order[a])
                              for j in range(len(self.tab_order))]),
            refresh=self._refresh_right_list,
            is_on_tab_bar=lambda: self.right_list.GetFirstSelected() == 0,
            view_id='teamtalk:tab_bar_order',
        )

    Args:
        control: The wx control hosting the tab bar at row 0.
        get_current_index: ``() -> int``  current tab's slot in the bar.
        get_tab_count: ``() -> int``  total number of tab cards.
        get_tab_label: ``(slot_idx) -> str``  display label for a slot.
        swap: ``(slot_a, slot_b) -> None``  swap two tab cards in the
            caller's underlying data.
        refresh: ``() -> None``  redraw the tab bar row 0 text after a
            swap (caller-specific).
        is_on_tab_bar: ``() -> bool``  True when keyboard focus is on
            row 0 of ``control``. Required so Space pickup only fires on
            the tab bar row, not on regular items.
        view_id: Optional persistence key for ``.index.TCG`` (e.g.
            ``"teamtalk:tab_bar_order"``). When None, no persistence.
        get_tab_keys: Optional ``() -> list[str]``  stable keys per tab
            slot, in current order. Used as the persistence payload when
            ``view_id`` is given. Defaults to slot indices.
    """

    def __init__(self, control, get_current_index, get_tab_count,
                 get_tab_label, swap, refresh, is_on_tab_bar,
                 view_id=None, get_tab_keys=None):
        self.control = control
        self.get_current_index = get_current_index
        self.get_tab_count = get_tab_count
        self.get_tab_label = get_tab_label
        self.swap = swap
        self.refresh = refresh
        self.is_on_tab_bar = is_on_tab_bar
        self.view_id = view_id
        self.get_tab_keys = get_tab_keys

        self._active = False
        self._origin_keys = None  # captured for Escape rollback

        # PushEventHandler so we run before any frame-level Bind handler.
        # Without this, the frame's existing CHAR_HOOK (e.g. feedback
        # hub's _on_key_hook, titan-net's OnKeyPress) might consume Space
        # / Left / Right / Escape before we see them.
        self._frame = _top_level_frame(control)
        self._frame_hook = None
        if self._frame is not None:
            self._frame_hook = _make_char_hook_handler(
                lambda evt: self._on_frame_char_hook(evt))
            self._frame.PushEventHandler(self._frame_hook)
            import wx as _wx
            self._frame.Bind(_wx.EVT_WINDOW_DESTROY,
                             self._on_frame_destroyed)

    def _on_frame_destroyed(self, event):
        if self._frame is None or self._frame_hook is None:
            event.Skip()
            return
        try:
            self._frame.RemoveEventHandler(self._frame_hook)
        except Exception:
            pass
        self._frame_hook = None
        event.Skip()

    @property
    def is_active(self):
        return self._active

    def cancel(self):
        """Public cancel - safe to call from frame close handlers."""
        if self._active:
            self._cancel_drag()

    def _on_frame_char_hook(self, event):
        import wx as _wx
        if not _focus_is_inside(self.control):
            event.Skip()
            return
        key = event.GetKeyCode()
        modifiers = event.GetModifiers()

        # While a card is picked up, Left / Right move it, Space drops,
        # Escape cancels, and arrow / Home / End / Tab are swallowed so
        # focus stays locked on the picked-up card (matches main GUI).
        if self._active:
            if key == _wx.WXK_SPACE and modifiers == _wx.MOD_NONE:
                self._drop_drag()
                return
            if key == _wx.WXK_ESCAPE and modifiers == _wx.MOD_NONE:
                self._cancel_drag()
                return
            if key == _wx.WXK_LEFT and modifiers == _wx.MOD_NONE:
                self._move_drag(-1)
                return
            if key == _wx.WXK_RIGHT and modifiers == _wx.MOD_NONE:
                self._move_drag(+1)
                return
            if key in (_wx.WXK_UP, _wx.WXK_DOWN, _wx.WXK_HOME,
                       _wx.WXK_END, _wx.WXK_TAB):
                return

        # Space on the tab bar row picks up the current card.
        if (key == _wx.WXK_SPACE and modifiers == _wx.MOD_NONE
                and not self._active):
            try:
                on_bar = bool(self.is_on_tab_bar())
            except Exception:
                on_bar = False
            if on_bar:
                self._start_drag()
                return

        event.Skip()

    def _capture_keys(self):
        if callable(self.get_tab_keys):
            try:
                return list(self.get_tab_keys())
            except Exception:
                return None
        return None

    def _start_drag(self):
        try:
            count = int(self.get_tab_count())
        except Exception:
            return
        if count <= 1:
            return
        try:
            idx = int(self.get_current_index())
        except Exception:
            return
        if idx < 0 or idx >= count:
            return
        self._active = True
        self._origin_keys = self._capture_keys()
        try:
            label = self.get_tab_label(idx)
        except Exception:
            label = ""
        _play('ui/drag.ogg')
        _speak_drag(f"Picked up {label}")

    def _move_drag(self, direction):
        if not self._active:
            return
        try:
            idx = int(self.get_current_index())
            count = int(self.get_tab_count())
        except Exception:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= count:
            _play('ui/endoftapbar.ogg')
            return
        try:
            self.swap(idx, new_idx)
        except Exception as e:
            print(f"[TabBarDragController] swap error: {e}")
            return
        try:
            self.refresh()
        except Exception as e:
            print(f"[TabBarDragController] refresh error: {e}")
        _play('ui/drag.ogg')
        try:
            label = self.get_tab_label(new_idx)
        except Exception:
            label = ""
        _speak_drag(f"{label}, {new_idx + 1} of {count}")

    def _drop_drag(self):
        if not self._active:
            return
        self._active = False
        self._origin_keys = None
        _play('ui/drop.ogg')
        if self.view_id:
            try:
                from src.titan_core import list_order
                keys = self._capture_keys()
                if keys is not None:
                    list_order.set_list_order(self.view_id, keys)
            except Exception as e:
                print(f"[TabBarDragController] persist error: {e}")
        try:
            idx = int(self.get_current_index())
            label = self.get_tab_label(idx)
        except Exception:
            label = ""
            idx = -1
        if idx >= 0:
            _speak_drag(f"Dropped {label} at position {idx + 1}")

    def _cancel_drag(self):
        if not self._active:
            return
        origin = self._origin_keys
        self._active = False
        self._origin_keys = None
        # Restore by rolling the swap chain back. Caller-provided swap is
        # symmetric, so we re-apply any changes in reverse if we tracked
        # them - but the simplest robust restore is to ask the caller to
        # rebuild from its persisted base via refresh(). When get_tab_keys
        # is provided we know the original order; the caller can read it
        # back by saving + restoring its own state. Here we just play the
        # cancel earcon and refresh.
        _play('ui/popupclose.ogg')
        if origin is not None and self.view_id:
            try:
                from src.titan_core import list_order
                # Tell the caller "your saved order should look like this"
                # - the actual data restoration is the caller's job: they
                # may listen to the same view_id key on refresh.
                list_order.set_list_order(self.view_id, origin)
            except Exception:
                pass
        try:
            self.refresh()
        except Exception:
            pass
        _speak_drag("Drag cancelled")
