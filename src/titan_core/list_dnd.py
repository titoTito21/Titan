"""Reusable drag-and-drop helpers for lists across Titan-Net, Titan IM
modules, components, the Elten client, and any other UI that wants the
same reorder behaviour as the main TCE GUI.

Two reorder paths are wired on every attached control:

* **Ctrl+Up / Ctrl+Down** moves the current selection one slot in that
  direction. ``ui/drop.ogg`` plays on a successful move; ``ui/endoflist.ogg``
  plays at the first/last data row.
* **Mouse drag** (left-press, drag past a small dead zone, release) drops
  the dragged item at the target index. ``ui/drag.ogg`` plays on pick-up
  and ``ui/drop.ogg`` plays on release.

The new order is persisted via :mod:`src.titan_core.list_order`, the same
``.index.TCG`` file that stores the main GUI's app/game/tab-bar order. Pass
a stable ``view_id`` (``"teamtalk:profiles"``, ``"elten:contacts"``, ...)
so each list keeps its own slot in that file.

Row 0 of the control may be a virtual tab bar (the first-row "tab bar"
convention used by the main GUI, the Feedback Hub and Titan IM modules).
Most lists do NOT have one - regular lists keep the default
``has_tab_bar=False`` and every row is movable. Only the lists that
actually inject a tab bar at row 0 should pass ``has_tab_bar=True``; the
helper then refuses to drag onto / off of row 0, leaving the tab bar
untouched.

Usage::

    from src.titan_core.list_dnd import attach_listbox_dnd, attach_listctrl_dnd

    attach_listbox_dnd(
        self.profile_list,
        view_id='teamtalk:profiles',
        has_tab_bar=False,
        item_key_func=lambda i, text, data: f"profile:{text}",
    )

    attach_listctrl_dnd(
        self.right_list,
        view_id='teamtalk:files',
        has_tab_bar=True,        # row 0 is the virtual tab bar
        column_count=3,
        item_key_func=lambda i, columns, data: f"file:{columns[0]}",
        is_reorderable=lambda data: True,  # called per row to gate movement
    )
"""

import wx

from src.titan_core import list_order


# ---------------------------------------------------------------------------
# Frame / focus helpers
# ---------------------------------------------------------------------------

def _top_level_frame(window):
    """Walk up the parent chain from ``window`` to the enclosing top-level
    wx.Frame / wx.Dialog. Returns None if none is found."""
    try:
        cur = window
        while cur is not None:
            if isinstance(cur, (wx.Frame, wx.Dialog)):
                return cur
            cur = cur.GetParent()
    except Exception:
        pass
    return None


def _focus_is_inside(widget):
    """Return True when keyboard focus is on ``widget`` (or a descendant)."""
    try:
        focused = wx.Window.FindFocus()
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


class _CharHookHandler(wx.EvtHandler):
    """Lightweight wx.EvtHandler we push onto a frame's chain so CHAR_HOOK
    reaches our callback before any Bind handler the frame already had.

    PushEventHandler installs us at the FRONT of the frame's event handler
    chain, so events hit our wrapper first - we Skip() to fall through
    when we don't want to handle the key.
    """

    def __init__(self, callback):
        super().__init__()
        self._callback = callback
        self.Bind(wx.EVT_CHAR_HOOK, self._dispatch)

    def _dispatch(self, event):
        try:
            self._callback(event)
        except Exception as exc:
            print(f"[list_dnd] CHAR_HOOK handler error: {exc}")
            event.Skip()


# ---------------------------------------------------------------------------
# Audio + speech helpers
# ---------------------------------------------------------------------------

def _play(name):
    """Play a sound file via the Titan sound system. Silent on failure."""
    try:
        from src.titan_core.sound import play_sound
        play_sound(name)
    except Exception:
        pass


def _is_screen_reader_running():
    """Best-effort detection of an active screen reader.

    Used to skip the manual ``speaker.speak()`` of position info during
    drag - SR users get the focused row text auto-announced and we don't
    want to stack the same "X, N of M" twice.
    """
    try:
        from src.accessibility.messages import is_screen_reader_running
        return bool(is_screen_reader_running())
    except Exception:
        return False


def _speak(text):
    """Speak ``text`` only when no real screen reader is active.

    SR users hear the focused row text auto-announced after a drop, so a
    second manual speak would duplicate. With SR off (or only platform-TTS
    fallback available), we DO speak so the user gets feedback.
    """
    if _is_screen_reader_running():
        return
    try:
        from src.accessibility.messages import get_messenger
        get_messenger().speaker.speak(text, interrupt=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# wx.ListBox
# ---------------------------------------------------------------------------

class _ListBoxDnD:
    """Internal controller wired by :func:`attach_listbox_dnd`."""

    def __init__(self, listbox, view_id, has_tab_bar, item_key_func,
                 on_reorder, persist, is_reorderable):
        self.listbox = listbox
        self.view_id = view_id
        self.has_tab_bar = bool(has_tab_bar)
        self.first = 1 if self.has_tab_bar else 0
        self.item_key_func = item_key_func or (
            lambda i, text, data: f"txt:{text}")
        self.on_reorder = on_reorder
        self.persist = persist
        self.is_reorderable = is_reorderable
        self._drag = None
        self._bind()

    def _bind(self):
        lb = self.listbox
        lb.Bind(wx.EVT_KEY_DOWN, self._on_key)
        lb.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        lb.Bind(wx.EVT_MOTION, self._on_motion)
        lb.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        # Many TCE frames bind their own EVT_CHAR_HOOK that swallows arrow
        # keys before they reach the widget (titan-net, elten, feedback
        # hub, teamtalk all do this for custom Up / Down navigation).
        # wxPython's Bind() ordering for the same event on the same window
        # is not a reliable chain - we use PushEventHandler instead, which
        # installs a higher-priority event handler at the front of the
        # frame's chain. CHAR_HOOK now always reaches our handler first;
        # if we don't handle the key we Skip() and the frame's own Bind
        # handlers run as before.
        self._frame = _top_level_frame(lb)
        self._frame_hook = None
        if self._frame is not None:
            self._frame_hook = _CharHookHandler(
                lambda evt: self._on_frame_char_hook(evt))
            self._frame.PushEventHandler(self._frame_hook)
            # Best-effort cleanup when the frame is destroyed.
            self._frame.Bind(wx.EVT_WINDOW_DESTROY, self._on_frame_destroyed)

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

    def _on_frame_char_hook(self, event):
        if not _focus_is_inside(self.listbox):
            event.Skip()
            return
        key = event.GetKeyCode()
        if event.ControlDown() and not event.AltDown() and not event.ShiftDown():
            if key in (wx.WXK_UP, wx.WXK_DOWN):
                direction = -1 if key == wx.WXK_UP else +1
                if self._kbd_move(direction):
                    return
        event.Skip()

    def _on_key(self, event):
        key = event.GetKeyCode()
        if event.ControlDown() and not event.AltDown() and not event.ShiftDown():
            if key in (wx.WXK_UP, wx.WXK_DOWN):
                direction = -1 if key == wx.WXK_UP else +1
                if self._kbd_move(direction):
                    return
        event.Skip()

    def _on_left_down(self, event):
        idx = self.listbox.HitTest(event.GetPosition())
        self._drag = None
        if (idx != wx.NOT_FOUND and idx >= self.first
                and self._row_movable(idx)):
            self._drag = {
                'from': idx,
                'active': False,
                'start': event.GetPosition(),
            }
        event.Skip()

    def _row_movable(self, idx):
        if not callable(self.is_reorderable):
            return True
        try:
            text = self.listbox.GetString(idx)
        except Exception:
            text = ""
        try:
            data = self.listbox.GetClientData(idx)
        except Exception:
            data = None
        try:
            return bool(self.is_reorderable(idx, text, data))
        except Exception:
            return True

    def _on_motion(self, event):
        drag = self._drag
        if drag and event.Dragging() and event.LeftIsDown():
            if not drag['active']:
                now = event.GetPosition()
                if abs(now.y - drag['start'].y) >= 6:
                    drag['active'] = True
                    _play('ui/drag.ogg')
        event.Skip()

    def _on_left_up(self, event):
        drag = self._drag
        self._drag = None
        if not drag or not drag['active']:
            event.Skip()
            return
        target = self.listbox.HitTest(event.GetPosition())
        if (target == wx.NOT_FOUND
                or target < self.first
                or target == drag['from']
                or not self._row_movable(target)):
            event.Skip()
            return
        self._move_to(drag['from'], target)

    def _kbd_move(self, direction):
        sel = self.listbox.GetSelection()
        if (sel == wx.NOT_FOUND or sel < self.first
                or not self._row_movable(sel)):
            return False
        target = sel + direction
        count = self.listbox.GetCount()
        if (target < self.first or target >= count
                or not self._row_movable(target)):
            try:
                _play('ui/endoflist.ogg')
            except Exception:
                pass
            return True
        self._move_to(sel, target)
        return True

    def _move_to(self, from_idx, to_idx):
        count = self.listbox.GetCount()
        if (from_idx < self.first or to_idx < self.first
                or from_idx >= count or to_idx >= count):
            return
        items = []
        for i in range(self.first, count):
            try:
                data = self.listbox.GetClientData(i)
            except Exception:
                data = None
            items.append((self.listbox.GetString(i), data))
        rel_from = from_idx - self.first
        rel_to = to_idx - self.first
        moved = items.pop(rel_from)
        items.insert(rel_to, moved)
        for i in range(count - 1, self.first - 1, -1):
            try:
                self.listbox.Delete(i)
            except Exception:
                pass
        for text, data in items:
            if data is None:
                self.listbox.Append(text)
            else:
                self.listbox.Append(text, clientData=data)
        new_sel = items.index(moved) + self.first
        try:
            self.listbox.SetSelection(new_sel)
        except Exception:
            pass
        _play('ui/drop.ogg')
        if self.persist:
            self._persist(items)
        if callable(self.on_reorder):
            try:
                self.on_reorder([k for k in self._keys(items)])
            except Exception:
                pass
        _speak(f"{moved[0]}, {new_sel - self.first + 1} of {len(items)}")

    def _keys(self, items):
        for i, (text, data) in enumerate(items):
            try:
                yield self.item_key_func(i, text, data)
            except Exception:
                yield f"txt:{text}"

    def _resolve_view_id(self):
        vid = self.view_id
        if callable(vid):
            try:
                return vid()
            except Exception as exc:
                print(f"[list_dnd] view_id callable error: {exc}")
                return None
        return vid

    def _persist(self, items):
        try:
            view_id = self._resolve_view_id()
            if view_id:
                list_order.set_list_order(view_id, list(self._keys(items)))
        except Exception:
            pass

    def apply_saved_order(self):
        """Reorder the listbox to match the saved order in ``.index.TCG``.

        Call this AFTER you've populated (Append/Insert) the listbox so
        the user's drag-and-drop order survives a Clear-and-repopulate
        cycle (every view switch in multi-view lists, every program
        launch). Newly added rows whose key isn't in the saved order keep
        their default position at the end - same contract as the main
        TCE GUI's _apply_saved_order_to_listbox.
        """
        try:
            view_id = self._resolve_view_id()
            if not view_id:
                return
            saved = list_order.get_list_order(view_id)
            if not saved:
                return
            count = self.listbox.GetCount()
            if count <= self.first:
                return
            items = []
            for i in range(self.first, count):
                try:
                    data = self.listbox.GetClientData(i)
                except Exception:
                    data = None
                items.append((self.listbox.GetString(i), data))

            def _key_of(it):
                idx_in_items, (text, data) = it
                try:
                    return self.item_key_func(idx_in_items, text, data)
                except Exception:
                    return f"txt:{text}"

            indexed = list(enumerate(items))
            ordered = list_order.apply_order(saved, indexed, _key_of)
            new_items = [it for _i, it in ordered]
            if new_items == items:
                return
            for i in range(count - 1, self.first - 1, -1):
                try:
                    self.listbox.Delete(i)
                except Exception:
                    pass
            for text, data in new_items:
                if data is None:
                    self.listbox.Append(text)
                else:
                    self.listbox.Append(text, clientData=data)
        except Exception as exc:
            print(f"[list_dnd] apply_saved_order error: {exc}")


def attach_listbox_dnd(listbox, view_id, has_tab_bar=False,
                       item_key_func=None, on_reorder=None, persist=True,
                       is_reorderable=None, auto_apply_on_focus=False):
    """Bind drag-and-drop reordering to a :class:`wx.ListBox`.

    Args:
        listbox: The wx.ListBox to enhance.
        view_id: Stable identifier (e.g. ``"teamtalk:profiles"``) used as
            the persistence key in ``.index.TCG``.
        has_tab_bar: When True, row 0 is treated as a virtual tab bar and
            never participates in DnD. Defaults to False - most lists do
            not have a tab bar and every row should be movable.
        item_key_func: Optional ``(index, text, client_data) -> str``. When
            omitted, the visible text is used as the key (``txt:<text>``).
        on_reorder: Optional callback ``(new_keys: list[str]) -> None``
            invoked after a successful move (after persistence).
        persist: When False, skip the ``list_order.set_list_order`` write.
            Use this for transient lists whose order isn't meaningful
            across restarts.
        is_reorderable: Optional ``(index, text, client_data) -> bool`` to
            gate individual rows. Useful for menus where some entries
            should not be user-orderable (e.g. fixed "Back" / "Disconnect"
            sentinels at the bottom).
        auto_apply_on_focus: When True, re-apply the saved order from
            ``.index.TCG`` every time the listbox receives EVT_SET_FOCUS.
            Use this for multi-view lists with many populate sites (Elten,
            Titan-Net what's-new etc.) where wiring every show_*_view to
            call ``apply_saved_order()`` manually is impractical. The
            re-apply is a no-op when items already match the saved order.

    Returns:
        The internal controller object - keep a reference if you need to
        unbind handlers later.
    """
    controller = _ListBoxDnD(listbox, view_id, has_tab_bar, item_key_func,
                             on_reorder, persist, is_reorderable)
    if auto_apply_on_focus:
        def _on_focus(event):
            try:
                controller.apply_saved_order()
            except Exception:
                pass
            event.Skip()
        listbox.Bind(wx.EVT_SET_FOCUS, _on_focus)
    return controller


# ---------------------------------------------------------------------------
# wx.ListCtrl (report mode, multiple columns)
# ---------------------------------------------------------------------------

class _ListCtrlDnD:
    """Internal controller wired by :func:`attach_listctrl_dnd`."""

    def __init__(self, listctrl, view_id, has_tab_bar, column_count,
                 item_key_func, is_reorderable, on_reorder, persist):
        self.lc = listctrl
        self.view_id = view_id
        self.has_tab_bar = bool(has_tab_bar)
        self.first = 1 if self.has_tab_bar else 0
        self.column_count = max(1, int(column_count or 1))
        self.item_key_func = item_key_func or (
            lambda i, columns, data: f"txt:{columns[0] if columns else ''}")
        self.is_reorderable = is_reorderable
        self.on_reorder = on_reorder
        self.persist = persist
        self._drag = None
        self._bind()

    def _bind(self):
        lc = self.lc
        lc.Bind(wx.EVT_KEY_DOWN, self._on_key)
        lc.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        lc.Bind(wx.EVT_MOTION, self._on_motion)
        lc.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        # See _ListBoxDnD._bind for the rationale - PushEventHandler so
        # CHAR_HOOK reaches us before any frame-level Bind handler.
        self._frame = _top_level_frame(lc)
        self._frame_hook = None
        if self._frame is not None:
            self._frame_hook = _CharHookHandler(
                lambda evt: self._on_frame_char_hook(evt))
            self._frame.PushEventHandler(self._frame_hook)
            self._frame.Bind(wx.EVT_WINDOW_DESTROY, self._on_frame_destroyed)

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

    def _on_frame_char_hook(self, event):
        if not _focus_is_inside(self.lc):
            event.Skip()
            return
        key = event.GetKeyCode()
        if event.ControlDown() and not event.AltDown() and not event.ShiftDown():
            if key in (wx.WXK_UP, wx.WXK_DOWN):
                direction = -1 if key == wx.WXK_UP else +1
                if self._kbd_move(direction):
                    return
        event.Skip()

    def _on_key(self, event):
        key = event.GetKeyCode()
        if event.ControlDown() and not event.AltDown() and not event.ShiftDown():
            if key in (wx.WXK_UP, wx.WXK_DOWN):
                direction = -1 if key == wx.WXK_UP else +1
                if self._kbd_move(direction):
                    return
        event.Skip()

    def _hit_test(self, point):
        try:
            idx, _flags = self.lc.HitTest(point)
            return idx
        except Exception:
            return wx.NOT_FOUND

    def _on_left_down(self, event):
        idx = self._hit_test(event.GetPosition())
        self._drag = None
        if idx != wx.NOT_FOUND and idx >= self.first and self._row_movable(idx):
            self._drag = {
                'from': idx,
                'active': False,
                'start': event.GetPosition(),
            }
        event.Skip()

    def _on_motion(self, event):
        drag = self._drag
        if drag and event.Dragging() and event.LeftIsDown():
            if not drag['active']:
                now = event.GetPosition()
                if abs(now.y - drag['start'].y) >= 6:
                    drag['active'] = True
                    _play('ui/drag.ogg')
        event.Skip()

    def _on_left_up(self, event):
        drag = self._drag
        self._drag = None
        if not drag or not drag['active']:
            event.Skip()
            return
        target = self._hit_test(event.GetPosition())
        if (target == wx.NOT_FOUND
                or target < self.first
                or target == drag['from']
                or not self._row_movable(target)):
            event.Skip()
            return
        self._move_to(drag['from'], target)

    def _row_movable(self, idx):
        if not callable(self.is_reorderable):
            return True
        try:
            data = self.lc.GetItemData(idx)
        except Exception:
            data = 0
        try:
            return bool(self.is_reorderable(idx, data))
        except Exception:
            return True

    def _kbd_move(self, direction):
        sel = self.lc.GetFirstSelected()
        if sel == -1 or sel < self.first or not self._row_movable(sel):
            return False
        target = sel + direction
        count = self.lc.GetItemCount()
        if (target < self.first or target >= count
                or not self._row_movable(target)):
            try:
                _play('ui/endoflist.ogg')
            except Exception:
                pass
            return True
        self._move_to(sel, target)
        return True

    def _read_row(self, idx):
        cols = []
        for c in range(self.column_count):
            try:
                cols.append(self.lc.GetItemText(idx, c))
            except Exception:
                cols.append("")
        try:
            data = self.lc.GetItemData(idx)
        except Exception:
            data = 0
        return cols, data

    def _write_row(self, idx, cols, data):
        try:
            self.lc.InsertItem(idx, cols[0] if cols else "")
            for c in range(1, self.column_count):
                self.lc.SetItem(idx, c, cols[c] if c < len(cols) else "")
            self.lc.SetItemData(idx, data)
        except Exception:
            pass

    def _move_to(self, from_idx, to_idx):
        count = self.lc.GetItemCount()
        if (from_idx < self.first or to_idx < self.first
                or from_idx >= count or to_idx >= count):
            return
        rows = [self._read_row(i) for i in range(self.first, count)]
        rel_from = from_idx - self.first
        rel_to = to_idx - self.first
        moved = rows.pop(rel_from)
        rows.insert(rel_to, moved)
        for i in range(count - 1, self.first - 1, -1):
            try:
                self.lc.DeleteItem(i)
            except Exception:
                pass
        for offset, (cols, data) in enumerate(rows):
            self._write_row(self.first + offset, cols, data)
        new_sel = rows.index(moved) + self.first
        try:
            self.lc.Select(new_sel)
            self.lc.Focus(new_sel)
            self.lc.EnsureVisible(new_sel)
        except Exception:
            pass
        _play('ui/drop.ogg')
        if self.persist:
            self._persist(rows)
        if callable(self.on_reorder):
            try:
                self.on_reorder(list(self._keys(rows)))
            except Exception:
                pass
        first_col = moved[0][0] if moved[0] else ""
        _speak(f"{first_col}, {new_sel - self.first + 1} of {len(rows)}")

    def _keys(self, rows):
        for i, (cols, data) in enumerate(rows):
            try:
                yield self.item_key_func(i, cols, data)
            except Exception:
                yield f"txt:{cols[0] if cols else ''}"

    def _resolve_view_id(self):
        vid = self.view_id
        if callable(vid):
            try:
                return vid()
            except Exception as exc:
                print(f"[list_dnd] view_id callable error: {exc}")
                return None
        return vid

    def _persist(self, rows):
        try:
            view_id = self._resolve_view_id()
            if view_id:
                list_order.set_list_order(view_id, list(self._keys(rows)))
        except Exception:
            pass

    def apply_saved_order(self):
        """Reorder the ListCtrl to match the saved order in ``.index.TCG``.

        Call after populating so DnD reorders survive view switches and
        program launches.
        """
        try:
            view_id = self._resolve_view_id()
            if not view_id:
                return
            saved = list_order.get_list_order(view_id)
            if not saved:
                return
            count = self.lc.GetItemCount()
            if count <= self.first:
                return
            rows = [self._read_row(i) for i in range(self.first, count)]

            def _key_of(it):
                idx_in_rows, (cols, data) = it
                try:
                    return self.item_key_func(idx_in_rows, cols, data)
                except Exception:
                    return f"txt:{cols[0] if cols else ''}"

            indexed = list(enumerate(rows))
            ordered = list_order.apply_order(saved, indexed, _key_of)
            new_rows = [r for _i, r in ordered]
            if new_rows == rows:
                return
            for i in range(count - 1, self.first - 1, -1):
                try:
                    self.lc.DeleteItem(i)
                except Exception:
                    pass
            for offset, (cols, data) in enumerate(new_rows):
                self._write_row(self.first + offset, cols, data)
        except Exception as exc:
            print(f"[list_dnd] apply_saved_order error: {exc}")


def attach_listctrl_dnd(listctrl, view_id, has_tab_bar=False,
                        column_count=1, item_key_func=None,
                        is_reorderable=None, on_reorder=None, persist=True):
    """Bind drag-and-drop reordering to a :class:`wx.ListCtrl` (report mode).

    Args:
        listctrl: The wx.ListCtrl in ``LC_REPORT`` style to enhance.
        view_id: Stable identifier used as the persistence key in
            ``.index.TCG`` (e.g. ``"teamtalk:files"``).
        has_tab_bar: When True, row 0 is the virtual tab bar and never
            participates in DnD. Defaults to False - most ListCtrls do not
            have a tab bar.
        column_count: Number of columns in the ListCtrl. The helper reads
            and re-inserts every column to preserve row content during
            reorders.
        item_key_func: Optional ``(index, columns, item_data) -> str``.
            When omitted, the first column's text is used as the key.
        is_reorderable: Optional ``(index, item_data) -> bool`` to gate
            individual rows. Useful when only some entries should be
            user-orderable (e.g. PM threads but not chat history).
        on_reorder: Optional callback ``(new_keys: list[str]) -> None``
            invoked after a successful move.
        persist: When False, skip the ``list_order.set_list_order`` write.

    Returns:
        The internal controller object.
    """
    return _ListCtrlDnD(listctrl, view_id, has_tab_bar, column_count,
                        item_key_func, is_reorderable, on_reorder, persist)
