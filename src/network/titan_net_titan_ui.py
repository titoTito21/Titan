# -*- coding: utf-8 -*-
"""Titan-Net, in Titan's own window.

The classic Titan-Net window (`titan_net_gui.TitanNetMainWindow`) grew its
own navigation - a menu you select into, a Back button, a listbox reused
across views. Every other list on this desktop is the SAME control: a
`TabbedListFrame` (`src/network/im_ui_common.py`) whose row 0 is a virtual
tab bar, whose Left/Right cycles the tabs, whose Up/Down carries the panned
focus cue, and whose Enter opens the row - the window Titan IM, the Elten
bridge, Cling and the Titan-Net remote services all are. So Titan-Net is
that window too here: the online users, the rooms and the forum are tabs of
one list, and a row opens a Titan-style subscreen.

Nothing new is invented. The data is the existing `TitanNetClient`; the
forum thread is the existing `ForumTopicWindow`; the mailbox is the existing
`mail_gui.MailFrame` (itself a `TabbedListFrame` already); a room and a
private conversation are a `_ChatFrame` built the same way as the rest. The
features that are windows of their own in the classic client - moderation,
the repository, the feedback hub, interactive games - are reached from a
`More` tab, so nothing is lost while the everyday lists match the desktop.
"""

from __future__ import annotations

import threading
import time
from typing import Any, List, Optional, Sequence, Tuple

import wx

from src.network.im_ui_common import (
    TabbedListFrame, speak_titannet, play_sound, _,
)


def _fullname(user: dict) -> str:
    name = str(user.get('full_name') or '').strip()
    return f" - {name}" if name else ''


class TitanNetWindow(TabbedListFrame):
    """The Titan-Net main window, as a Titan tabbed list."""

    VIEW_ID = 'titannet'
    CLOSE_SOUND = 'ui/window_close.ogg'

    def __init__(self, parent, titan_client):
        self.titan_client = titan_client
        self.is_moderator = False
        self.is_developer = False
        self._blocked_ids: set = set()
        title = _("Titan-Net")
        try:
            who = getattr(titan_client, 'username', '') or ''
            number = getattr(titan_client, 'titan_number', '') or ''
            if who:
                title = _("Titan-Net - {user} (#{number})").format(user=who,
                                                                   number=number)
        except Exception:
            pass
        super().__init__(parent, title, size=(760, 600))
        self._load_role()
        self.refresh()
        # Live lists: the online users and the current tab refresh on their
        # own, the way the classic window's auto-refresh timer does, and a
        # background refresh never moves the keyboard (TabbedListFrame keeps
        # focus by row identity).
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda _e: self._tick(), self._timer)
        self._timer.Start(15000)
        try:
            play_sound('ui/window_open.ogg')
        except Exception:
            pass

    # -------------------------------------------------------------- tabs
    def build_tabs(self) -> Sequence[Tuple[str, str]]:
        tabs = [
            ('users', _("Online users")),
            ('rooms', _("Chat rooms")),
            ('forum', _("Forum")),
            ('pm', _("Private messages")),
            ('mail', _("Mail")),
            ('more', _("More")),
        ]
        return tabs

    # ------------------------------------------------------------- rows
    def load_items(self, tab_id: str, background: bool = False) -> None:
        if tab_id == 'more':
            self.apply_items(self._more_entries(), tab_id, background=background)
            return
        if tab_id == 'mail':
            # Mail is its own Titan window (a TabbedListFrame already); the
            # tab is a single row that opens it, so the mailbox is not
            # duplicated here.
            self.apply_items([{'kind': 'open_mail',
                               'label': _("Open the mailbox")}],
                             tab_id, background=background)
            return

        def worker():
            items = self._fetch(tab_id)
            wx.CallAfter(self.apply_items, items, tab_id, background=background)

        threading.Thread(target=worker, daemon=True).start()

    def _fetch(self, tab_id: str) -> List[Any]:
        client = self.titan_client
        try:
            if tab_id in ('users', 'pm'):
                result = client.get_online_users()
                return list(result.get('users', [])) if result.get('success') else []
            if tab_id == 'rooms':
                result = client.get_rooms()
                return list(result.get('rooms', [])) if result.get('success') else []
            if tab_id == 'forum':
                result = client.get_forum_topics(limit=50)
                return list(result.get('topics', [])) if result.get('success') else []
        except Exception as exc:
            print(f"[TITAN-NET UI] fetch {tab_id} failed: {exc}")
        return []

    def format_row(self, item: Any) -> str:
        tab = self.current_tab
        if isinstance(item, dict) and 'label' in item and 'kind' in item:
            return str(item['label'])
        if tab in ('users', 'pm'):
            number = item.get('titan_number', 'N/A')
            row = f"{item.get('username', '?')} (#{number}){_fullname(item)}"
            if item.get('id') in self._blocked_ids:
                row += " - " + _("blocked")
            return row
        if tab == 'rooms':
            row = str(item.get('name', '?'))
            count = item.get('user_count')
            if count is not None:
                row += " - " + _("{n} here").format(n=count)
            if item.get('has_password'):
                row += " - " + _("password")
            return row
        if tab == 'forum':
            title = str(item.get('title', '?'))
            author = item.get('author_username', '')
            replies = item.get('reply_count', 0)
            pin = "* " if item.get('is_pinned') else ''
            return f"{pin}{title} - {author} ({replies} {_('replies')})"
        return str(item)

    def row_key(self, item: Any) -> str:
        if isinstance(item, dict):
            for attr in ('id', 'topic_id', 'room_id'):
                if item.get(attr):
                    return f"{attr}:{item[attr]}"
            if item.get('username'):
                return f"user:{item['username']}"
            if item.get('label'):
                return f"label:{item['label']}"
        return ''

    def status_text(self) -> str:
        n = len(self.items)
        return _("{tab}: {n}").format(tab=self.tab_label(self.current_tab), n=n)

    # -------------------------------------------------------- activation
    def activate(self, item: Any) -> None:
        tab = self.current_tab
        if isinstance(item, dict) and item.get('kind'):
            self._run_entry(item)
            return
        if tab == 'users':
            self._user_actions(item)
        elif tab == 'pm':
            self._open_private_chat(item)
        elif tab == 'rooms':
            self._open_room(item)
        elif tab == 'forum':
            self._open_topic(item)

    def context_menu_items(self, item):
        tab = self.current_tab
        if tab in ('users', 'pm') and isinstance(item, dict) and item.get('username'):
            entries = [
                (_("Send a private message"), lambda: self._open_private_chat(item)),
                (_("Profile"), lambda: self._show_profile(item)),
            ]
            if item.get('id') in self._blocked_ids:
                entries.append((_("Unblock"), lambda: self._set_block(item, False)))
            else:
                entries.append((_("Block"), lambda: self._set_block(item, True)))
            return entries
        if tab == 'rooms' and isinstance(item, dict):
            return [(_("Join"), lambda: self._open_room(item))]
        if tab == 'forum' and isinstance(item, dict):
            return [(_("Open"), lambda: self._open_topic(item))]
        return ()

    def row_sound(self, item, index):
        # An unread private conversation or an unread topic gets the same
        # extra cue the rest of Titan uses; the data does not always carry
        # it, so this is best-effort and silent when it cannot tell.
        try:
            if isinstance(item, dict) and item.get('unread'):
                play_sound('ui/unread.ogg')
        except Exception:
            pass

    # ---------------------------------------------------------- the More tab
    def _more_entries(self):
        rows = [
            {'kind': 'whats_new', 'label': _("What's new")},
            {'kind': 'groups', 'label': _("Groups")},
            {'kind': 'repository', 'label': _("App repository")},
            {'kind': 'feedback', 'label': _("Feedback Hub")},
            {'kind': 'games', 'label': _("Interactive games")},
            {'kind': 'blocked', 'label': _("Blocked users")},
            {'kind': 'account', 'label': _("Recovery email")},
        ]
        if self.is_moderator:
            rows.append({'kind': 'moderation', 'label': _("Moderation")})
        rows.append({'kind': 'disconnect', 'label': _("Disconnect")})
        return rows

    def _run_entry(self, item):
        kind = item.get('kind')
        if kind == 'open_mail':
            self._open_mail()
        elif kind == 'disconnect':
            self._disconnect()
        else:
            # Everything else is a window the classic client already builds
            # Titan-style; open it through a shared, lazily-imported bridge so
            # this window carries none of that weight.
            self._open_classic_feature(kind)

    # -------------------------------------------------------- subscreens
    def _open_topic(self, item):
        try:
            from src.network.titan_net_gui import ForumTopicWindow
            win = ForumTopicWindow(self, self.titan_client, item.get('id'),
                                   item.get('title', ''))
            win.Show()
        except Exception as exc:
            print(f"[TITAN-NET UI] forum topic failed: {exc}")
            speak_titannet(_("The topic could not be opened."))

    def _open_room(self, item):
        _ChatFrame(self, self.titan_client, kind='room',
                   target_id=item.get('id'), title=item.get('name', '')).Show()

    def _open_private_chat(self, item):
        _ChatFrame(self, self.titan_client, kind='private',
                   target_id=item.get('id'),
                   title=item.get('username', '')).Show()

    def _open_mail(self):
        try:
            from src.network.mail_gui import show_mail_client
            show_mail_client(self, self.titan_client)
        except Exception as exc:
            print(f"[TITAN-NET UI] mail failed: {exc}")
            speak_titannet(_("Mail could not be opened."))

    def _show_profile(self, item):
        speak_titannet(_("{user}, number {number}").format(
            user=item.get('username', ''), number=item.get('titan_number', '')))

    def _user_actions(self, item):
        # Enter on a user offers the same short list the context menu does,
        # as a real menu - which is what a user row does everywhere on this
        # desktop.
        entries = self.context_menu_items(item)
        if not entries:
            return
        menu = wx.Menu()
        handlers = {}
        for label, handler in entries:
            mi = menu.Append(wx.ID_ANY, label)
            handlers[mi.GetId()] = handler
        menu.Bind(wx.EVT_MENU, lambda e: handlers.get(e.GetId(), lambda: None)())
        self.listbox.PopupMenu(menu)
        menu.Destroy()

    def _set_block(self, item, block):
        def worker():
            try:
                if block:
                    self.titan_client.block_user(item.get('id'))
                    self._blocked_ids.add(item.get('id'))
                else:
                    self.titan_client.unblock_user(item.get('id'))
                    self._blocked_ids.discard(item.get('id'))
            except Exception as exc:
                print(f"[TITAN-NET UI] block failed: {exc}")
            wx.CallAfter(self.refresh, True)
        threading.Thread(target=worker, daemon=True).start()

    def _open_classic_feature(self, kind):
        """Open one of the classic window's own Titan-style feature windows.

        These are already separate windows in the classic client; this
        borrows the method that opens each so a feature is written once.
        """
        try:
            from src.network import titan_net_gui as classic
        except Exception as exc:
            print(f"[TITAN-NET UI] classic import failed: {exc}")
            return
        # A hidden classic window carries the feature openers; build one lazily
        # and keep it, so the heavy features work exactly as before.
        helper = getattr(self, '_classic_helper', None)
        if helper is None or not _alive(helper):
            try:
                helper = classic.TitanNetMainWindow(self, self.titan_client)
                helper.Hide()
                self._classic_helper = helper
            except Exception as exc:
                print(f"[TITAN-NET UI] classic helper failed: {exc}")
                return
        opener = {
            'whats_new': 'show_whats_new_view',
            'groups': 'show_groups_view',
            'repository': 'show_repository_view',
            'feedback': 'open_feedback_hub',
            'games': 'open_interactive_games',
            'blocked': 'show_blocked_users_dialog',
            'account': '_manage_recovery_email',
            'moderation': 'show_moderation_menu',
        }.get(kind)
        method = getattr(helper, opener, None) if opener else None
        if method is None:
            speak_titannet(_("That feature is not available."))
            return
        try:
            if opener in ('show_blocked_users_dialog', '_manage_recovery_email'):
                method()
            else:
                helper.Show()
                helper.Raise()
                method()
        except Exception as exc:
            print(f"[TITAN-NET UI] feature {kind} failed: {exc}")

    def _disconnect(self):
        try:
            self.titan_client.disconnect()
        except Exception:
            pass
        self.Close()

    # ------------------------------------------------------------- state
    def _load_role(self):
        def worker():
            try:
                info = self.titan_client.get_my_info() if hasattr(
                    self.titan_client, 'get_my_info') else {}
                role = (info or {}).get('role', 'user')
            except Exception:
                role = 'user'
            self.is_moderator = role in ('moderator', 'developer', 'admin')
            self.is_developer = role in ('developer', 'admin')
            wx.CallAfter(self.rebuild_tabs)
        threading.Thread(target=worker, daemon=True).start()

    def _tick(self):
        if self._closing:
            return
        self.refresh(background=True)

    def on_closed(self):
        try:
            if self._timer.IsRunning():
                self._timer.Stop()
        except Exception:
            pass


def _alive(window) -> bool:
    if window is None:
        return False
    try:
        return bool(window) and not window.IsBeingDeleted()
    except Exception:
        return False


class _ChatFrame(TabbedListFrame):
    """A room or a private conversation, as a Titan list with an input.

    The messages are the list (newest last), the tab bar carries the one
    conversation, an input sits under it (Enter sends, Shift+Enter is a
    newline), and Escape leaves. It reads and sends through the same
    `TitanNetClient` the classic room view does; the difference is only that
    it is the same window as everything else.
    """

    def __init__(self, parent, titan_client, kind, target_id, title):
        self.titan_client = titan_client
        self.kind = kind
        self.target_id = target_id
        self._title = title
        self._joined = False
        super().__init__(parent, self._frame_title(), size=(760, 600))
        if kind == 'room':
            self._join()
        self.refresh()
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda _e: self.refresh(background=True), self._timer)
        self._timer.Start(4000)

    def _frame_title(self):
        if self.kind == 'room':
            return _("Room: {name}").format(name=self._title)
        return _("Conversation with {user}").format(user=self._title)

    def build_tabs(self):
        return [('chat', self._title or _("Conversation"))]

    def build_footer(self, sizer):
        self.input = wx.TextCtrl(self.panel,
                                 style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER,
                                 size=(-1, 70))
        self.input.Bind(wx.EVT_KEY_DOWN, self._on_input_key)
        sizer.Add(self.input, flag=wx.EXPAND | wx.ALL, border=8)

    def load_items(self, tab_id, background=False):
        def worker():
            items = self._fetch()
            wx.CallAfter(self.apply_items, items, tab_id, background=background)
        threading.Thread(target=worker, daemon=True).start()

    def _fetch(self):
        try:
            if self.kind == 'room':
                result = self.titan_client.get_room_messages(self.target_id)
            else:
                result = self.titan_client.get_private_messages(self.target_id)
            if result.get('success'):
                return list(result.get('messages', []))
        except Exception as exc:
            print(f"[TITAN-NET UI] chat fetch failed: {exc}")
        return []

    def format_row(self, item):
        who = item.get('sender_username') or item.get('username') or item.get('from') or '?'
        text = item.get('message') or item.get('content') or item.get('text') or ''
        return f"{who}: {text}"

    def row_key(self, item):
        mid = item.get('id') or item.get('msg_id')
        return f"msg:{mid}" if mid else ''

    def activate(self, item):
        # Enter on a message reads the whole of it, for a long one.
        who = item.get('sender_username') or item.get('username') or '?'
        text = item.get('message') or item.get('content') or ''
        from src.network.im_ui_common import show_message
        show_message(self, f"{who}\n\n{text}", _("Message"))

    def _on_input_key(self, event):
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) \
                and not event.ShiftDown():
            self._send()
            return
        event.Skip()

    def _send(self):
        text = self.input.GetValue().strip()
        if not text:
            return
        self.input.SetValue('')

        def worker():
            try:
                if self.kind == 'room':
                    self.titan_client.send_room_message(self.target_id, text)
                else:
                    self.titan_client.send_private_message(self.target_id, text)
            except Exception as exc:
                print(f"[TITAN-NET UI] send failed: {exc}")
            wx.CallAfter(self.refresh, True)
        threading.Thread(target=worker, daemon=True).start()

    def _join(self):
        try:
            self.titan_client.join_room(self.target_id)
            self._joined = True
        except Exception as exc:
            print(f"[TITAN-NET UI] join failed: {exc}")

    def on_closed(self):
        try:
            if self._timer.IsRunning():
                self._timer.Stop()
        except Exception:
            pass
        if self.kind == 'room' and self._joined:
            try:
                self.titan_client.leave_room(self.target_id)
            except Exception:
                pass
