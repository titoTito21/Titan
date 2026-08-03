# -*- coding: utf-8 -*-
"""Shared accessibility scaffolding for the Titan IM clients.

WhatsApp and Messenger get their own dedicated windows - their tabs, menus and
dialogs differ - but the *interaction* must be identical to the rest of Titan.
That part lives here, once:

* row 0 of the list is the **tab bar** (``clientData {'type': 'tab_bar'}``),
  Left/Right and Ctrl+Tab cycle it, the end of the bar earcons instead of
  wrapping, and switching a tab always lands focus back on row 0;
* every focus change plays the stereo-panned focus cue (left at the first row,
  right at the last), the tab-bar row plays its own earcon plus the SR-only
  "Tab bar" marker, and running off the list plays the end-of-list sound;
* Enter activates, the Applications key opens a per-row context menu, F5
  refreshes, Escape goes back one level and only then closes.

The speech and tab-bar helpers are *reused* from ``feedback_hub`` rather than
copied, so all three views keep announcing things the same way. Sounds come from
``titanim_sound_api`` - the Titan-Net set every Titan IM integration shares.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import wx

from src.settings.settings import get_setting
from src.titan_core.sound import (
    play_sound,
    initialize_sound,
    play_focus_sound,
    play_endoflist_sound,
)
from src.titan_core.skin_manager import apply_skin_to_window
from src.titan_core.translation import set_language

_ = set_language(get_setting('language', 'pl'))

# ---------------------------------------------------------------------------
# Reused announcement helpers - identical behaviour to the Feedback Hub and
# Titan-Net views. Imported lazily-with-fallback so a broken optional import
# can never keep a messaging client from opening.
# ---------------------------------------------------------------------------
try:
    from src.network.feedback_hub import (
        speak_titannet, speak_notification, _announce_tab_bar as announce_tab_bar,
    )
except Exception as _exc:  # pragma: no cover - only on a broken install
    print(f"[Titan IM UI] announcement helpers unavailable: {_exc}")

    def speak_titannet(text, position=0.0, pitch_offset=0, interrupt=True):
        print(f"[Titan IM UI] {text}")

    def speak_notification(text, notification_type='info', play_sound_effect=True):
        print(f"[Titan IM UI] {text}")

    def announce_tab_bar():
        try:
            play_sound('ui/tapbar.ogg')
        except Exception:
            pass

try:
    from src.network.titanim_sound_api import TitanIMSoundAPI
    sounds = TitanIMSoundAPI()
except Exception as _exc:  # pragma: no cover
    print(f"[Titan IM UI] sound API unavailable: {_exc}")
    sounds = None

try:
    initialize_sound()
except Exception as _exc:
    print(f"[Titan IM UI] initialize_sound() failed: {_exc}")


TAB_BAR_MARKER = {'type': 'tab_bar'}


def apply_skin_tree(window) -> None:
    """Apply the active Titan skin to a window and everything inside it."""
    try:
        apply_skin_to_window(window)
    except Exception:
        return
    for child in window.GetChildren():
        apply_skin_tree(child)


def show_message(parent, message: str, caption: str,
                 style=wx.OK | wx.ICON_INFORMATION) -> int:
    dialog = wx.MessageDialog(parent, message, caption, style)
    apply_skin_tree(dialog)
    result = dialog.ShowModal()
    dialog.Destroy()
    return result


def format_time(timestamp: float) -> str:
    """Short, speakable time: today's messages get a clock, older ones a date."""
    if not timestamp:
        return ''
    seconds = timestamp / 1000.0 if timestamp > 1e11 else timestamp
    now = time.time()
    try:
        if now - seconds < 20 * 3600:
            return time.strftime('%H:%M', time.localtime(seconds))
        return time.strftime('%d.%m %H:%M', time.localtime(seconds))
    except Exception:
        return ''


def pan_for(index: int, count: int) -> float:
    """Stereo pan for row ``index`` of ``count`` real rows: 0.0 left, 1.0 right."""
    if count <= 1:
        return 0.5
    return max(0.0, min(1.0, index / float(count - 1)))


class TabbedListFrame(wx.Frame):
    """A frame whose list carries a virtual tab bar in row 0.

    Subclasses provide the tabs, the rows and what activation means; everything
    about *how it feels* is handled here.
    """

    VIEW_ID = 'titan_im'
    LIST_LABEL = ''

    def __init__(self, parent, title: str, size: Tuple[int, int] = (960, 680)):
        super().__init__(parent, title=title, size=size)

        self.tabs: List[Tuple[str, str]] = []
        self.current_tab: str = ''
        self.items: List[Any] = []
        self._last_focus_idx = 0
        self._closing = False

        self.panel = wx.Panel(self)
        self._sizer = wx.BoxSizer(wx.VERTICAL)

        self.header = wx.StaticText(self.panel, label=title)
        self._sizer.Add(self.header, flag=wx.ALL, border=8)

        self.build_toolbar(self._sizer)

        if self.LIST_LABEL:
            self._sizer.Add(wx.StaticText(self.panel, label=self.LIST_LABEL),
                            flag=wx.LEFT | wx.RIGHT | wx.TOP, border=8)

        self.listbox = wx.ListBox(self.panel, style=wx.LB_SINGLE)
        self.listbox.Bind(wx.EVT_LISTBOX, self._on_select)
        self.listbox.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._activate_selected())
        self.listbox.Bind(wx.EVT_CONTEXT_MENU, lambda e: self._open_context_menu())
        self._sizer.Add(self.listbox, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)

        self.build_footer(self._sizer)

        self.CreateStatusBar()
        self.panel.SetSizer(self._sizer)

        self.Bind(wx.EVT_CHAR_HOOK, self._on_key_hook)
        self.Bind(wx.EVT_CLOSE, self._on_close_event)

        self.tabs = [(tab_id, label) for tab_id, label in self.build_tabs()]
        if self.tabs:
            self.current_tab = self.tabs[0][0]

        apply_skin_tree(self)

    # ---------------------------------------------------------- to override
    def build_tabs(self) -> Sequence[Tuple[str, str]]:
        """Return ``[(tab_id, label), ...]`` - the top tab bar."""
        return []

    def build_toolbar(self, sizer: wx.BoxSizer) -> None:
        """Optional buttons above the list."""

    def build_footer(self, sizer: wx.BoxSizer) -> None:
        """Optional controls below the list (a message input, for example)."""

    def load_items(self, tab_id: str, background: bool = False) -> None:
        """Fetch the rows for ``tab_id`` and hand them to ``apply_items``.

        ``background`` marks a refresh the user did not ask for (live data
        arriving on its own): it must never move focus or take it away.
        """
        self.apply_items([], tab_id, background=background)

    def row_key(self, item: Any) -> str:
        """Stable identity of a row, used to keep focus across a refresh.

        Live lists reorder - a chat that gets a message jumps to the top - so
        the row the user is reading is followed by identity, not by index.
        """
        for attribute in ('id', 'chat_id', 'msg_id'):
            value = getattr(item, attribute, None)
            if value:
                return f"{attribute}:{value}"
        return ''

    def format_row(self, item: Any) -> str:
        return str(item)

    def activate(self, item: Any) -> None:
        """Enter on a row."""

    def context_menu_items(self, item: Any) -> Sequence[Tuple[str, Callable[[], None]]]:
        return ()

    def extra_key(self, keycode: int, modifiers: int, item: Optional[Any]) -> bool:
        """Handle a key the base class does not. Return True when consumed."""
        return False

    def on_escape(self) -> bool:
        """Return True to close the window, False when a level was popped."""
        return True

    def on_closed(self) -> None:
        """Called once, after the window really closes."""

    def row_sound(self, item: Any, index: int) -> None:
        """Optional extra earcon for a focused row (unread, media, ...)."""

    def status_text(self) -> str:
        return _("{tab}: {n} entries").format(tab=self.tab_label(self.current_tab),
                                              n=len(self.items))

    # ------------------------------------------------------------- tab bar
    def tab_label(self, tab_id: str) -> str:
        for candidate, label in self.tabs:
            if candidate == tab_id:
                return label
        return tab_id

    def tab_index(self, tab_id: str) -> int:
        for index, (candidate, _label) in enumerate(self.tabs):
            if candidate == tab_id:
                return index
        return 0

    def tab_bar_text(self) -> str:
        return _("{}, {} of {}").format(self.tab_label(self.current_tab),
                                        self.tab_index(self.current_tab) + 1,
                                        len(self.tabs))

    def is_tab_bar_row(self, index: int) -> bool:
        if index != 0 or self.listbox.GetCount() == 0:
            return False
        try:
            data = self.listbox.GetClientData(0)
        except Exception:
            return False
        return isinstance(data, dict) and data.get('type') == 'tab_bar'

    def cycle_tab(self, direction: int) -> None:
        index = self.tab_index(self.current_tab) + direction
        if index < 0 or index >= len(self.tabs):
            try:
                play_sound('ui/endoftapbar.ogg')
            except Exception:
                pass
            return
        self.current_tab = self.tabs[index][0]
        try:
            play_sound('ui/switch_list.ogg')
        except Exception:
            pass
        self.refresh()

    def rebuild_tabs(self) -> None:
        """Re-evaluate the tab set (capabilities can arrive after opening)."""
        previous = self.current_tab
        self.tabs = [(tab_id, label) for tab_id, label in self.build_tabs()]
        if not self.tabs:
            return
        if previous not in [tab_id for tab_id, _label in self.tabs]:
            previous = self.tabs[0][0]
        self.current_tab = previous
        if self.listbox.GetCount():
            self.listbox.SetString(0, self.tab_bar_text())

    # ---------------------------------------------------------------- rows
    def refresh(self, background: bool = False) -> None:
        self.load_items(self.current_tab, background=background)

    def apply_items(self, items: Sequence[Any], tab_id: str = '',
                    keep_focus: bool = False, background: bool = False) -> None:
        """Replace the rows. Row 0 is always the tab bar.

        A ``background`` refresh is data arriving by itself. It rewrites the
        rows underneath the user: the row they are on keeps the focus (matched
        by identity, so a reordered list does not move them), focus is never
        taken, and an unchanged list is not touched at all - the same quiet
        behaviour Elten has.
        """
        if self._closing:
            return
        if tab_id and tab_id != self.current_tab:
            return  # the user switched tabs while the request was in flight

        items = list(items)
        rows = [self.format_row(item) for item in items]

        if background and not self._rows_changed(rows):
            # Same list as on screen: rebuilding it would only make the screen
            # reader re-read the row and reset the caret for nothing.
            self.items = items
            self.SetStatusText(self.status_text())
            return

        keep_focus = keep_focus or background
        previous = self.listbox.GetSelection() if keep_focus else 0
        focused_key = ''
        if keep_focus and previous > 0:
            position = previous - 1
            if 0 <= position < len(self.items):
                focused_key = self.row_key(self.items[position])

        self.items = items
        self.listbox.Freeze()
        try:
            self.listbox.Clear()
            self.listbox.Append(self.tab_bar_text(), dict(TAB_BAR_MARKER))
            for index, item in enumerate(self.items):
                self.listbox.Append(rows[index], item)
        finally:
            self.listbox.Thaw()

        target = 0
        if keep_focus:
            moved = self._index_of_key(focused_key) if focused_key else -1
            if moved > 0:
                target = moved
            elif 0 <= previous < self.listbox.GetCount():
                target = previous
            else:
                target = max(0, self.listbox.GetCount() - 1)
        self.listbox.SetSelection(target)
        self._last_focus_idx = target
        if not keep_focus:
            # Switching tabs never drops focus onto a real row: the same
            # contract as TitanApp's list views, so Left/Right keeps cycling.
            self.listbox.SetFocus()
        self.SetStatusText(self.status_text())

    def _rows_changed(self, rows: Sequence[str]) -> bool:
        """True when the rendered rows differ from what is on screen."""
        if self.listbox.GetCount() != len(rows) + 1:
            return True
        for index, text in enumerate(rows):
            if self.listbox.GetString(index + 1) != text:
                return True
        return False

    def _index_of_key(self, key: str) -> int:
        """Listbox row (tab bar included) holding the item with ``key``."""
        for position, item in enumerate(self.items):
            if self.row_key(item) == key:
                return position + 1
        return -1

    def selected_item(self) -> Optional[Any]:
        index = self.listbox.GetSelection()
        if index <= 0:
            return None
        position = index - 1
        if 0 <= position < len(self.items):
            return self.items[position]
        return None

    def select_item_index(self, position: int) -> None:
        """Focus real row ``position`` (0-based, tab bar excluded)."""
        target = position + 1
        if 0 <= target < self.listbox.GetCount():
            self.listbox.SetSelection(target)
            self.emit_focus_feedback(target)

    # ------------------------------------------------------------- feedback
    def emit_focus_feedback(self, index: int) -> None:
        if self.is_tab_bar_row(index):
            announce_tab_bar()
            self._last_focus_idx = index
            return

        real_count = max(0, self.listbox.GetCount() - 1)
        try:
            play_focus_sound(pan=pan_for(index - 1, real_count))
        except Exception:
            pass

        position = index - 1
        if 0 <= position < len(self.items) and index != self._last_focus_idx:
            try:
                self.row_sound(self.items[position], position)
            except Exception:
                pass
        self._last_focus_idx = index

    # --------------------------------------------------------------- events
    def _on_select(self, event) -> None:
        index = self.listbox.GetSelection()
        if index >= 0:
            self.emit_focus_feedback(index)

    def _activate_selected(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        try:
            play_sound('core/SELECT.ogg')
        except Exception:
            pass
        self.activate(item)

    def _open_context_menu(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        entries = list(self.context_menu_items(item))
        if not entries:
            return
        menu = wx.Menu()
        handlers: Dict[int, Callable[[], None]] = {}
        for label, handler in entries:
            menu_item = menu.Append(wx.ID_ANY, label)
            handlers[menu_item.GetId()] = handler
        try:
            play_sound('ui/contextmenu.ogg')
        except Exception:
            pass

        def _dispatch(event):
            handler = handlers.get(event.GetId())
            if handler:
                handler()

        menu.Bind(wx.EVT_MENU, _dispatch)
        self.listbox.PopupMenu(menu)
        menu.Destroy()
        try:
            play_sound('ui/contextmenuclose.ogg')
        except Exception:
            pass

    def _on_key_hook(self, event: wx.KeyEvent) -> None:
        keycode = event.GetKeyCode()
        modifiers = event.GetModifiers()
        focus = self.FindFocus()

        if keycode == wx.WXK_ESCAPE and modifiers == wx.MOD_NONE:
            if self.on_escape():
                try:
                    play_sound('ui/popupclose.ogg')
                except Exception:
                    pass
                self.Close()
            return

        if keycode == wx.WXK_F5 and modifiers == wx.MOD_NONE:
            self.refresh()
            return

        if keycode == wx.WXK_TAB and modifiers == wx.MOD_CONTROL:
            self.cycle_tab(+1)
            return
        if keycode == wx.WXK_TAB and modifiers == (wx.MOD_CONTROL | wx.MOD_SHIFT):
            self.cycle_tab(-1)
            return

        if focus is self.listbox:
            index = self.listbox.GetSelection()
            count = self.listbox.GetCount()

            if keycode in (wx.WXK_LEFT, wx.WXK_RIGHT):
                if self.is_tab_bar_row(index):
                    self.cycle_tab(-1 if keycode == wx.WXK_LEFT else +1)
                # Left/Right belongs to the tab bar - swallow it elsewhere so it
                # cannot move the selection.
                return

            if keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and not event.AltDown():
                self._activate_selected()
                return

            if keycode in (wx.WXK_WINDOWS_MENU, wx.WXK_MENU):
                self._open_context_menu()
                return

            if self.extra_key(keycode, modifiers, self.selected_item()):
                return

            # Arrow keys are handled by hand so the focus cue, the end-of-list
            # earcon and the "Tab bar" marker fire on every move - EVT_LISTBOX
            # is not raised for programmatic selection on Windows.
            new_index = index
            if keycode == wx.WXK_UP:
                new_index = index - 1
            elif keycode == wx.WXK_DOWN:
                new_index = index + 1
            elif keycode == wx.WXK_HOME:
                new_index = 0
            elif keycode == wx.WXK_END:
                new_index = count - 1
            else:
                event.Skip()
                return

            if 0 <= new_index < count and new_index != index:
                self.listbox.SetSelection(new_index)
                self.emit_focus_feedback(new_index)
            else:
                try:
                    play_endoflist_sound()
                except Exception:
                    pass
            return

        if self.extra_key(keycode, modifiers, None):
            return
        event.Skip()

    def _on_close_event(self, event) -> None:
        self._closing = True
        try:
            self.on_closed()
        except Exception as exc:
            print(f"[Titan IM UI] on_closed failed: {exc}")
        try:
            if sounds:
                sounds.window_close()
        except Exception:
            pass
        event.Skip()
