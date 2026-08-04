# -*- coding: utf-8 -*-
"""Common plumbing behind the two dedicated Titan IM clients.

The WhatsApp and Messenger windows are separate on purpose - different tabs,
different menus, different login flows. What they must *not* differ in is the
boring part: how backend events become sounds and speech, when a notification
fires, how a conversation opens, how the raw page is offered for a login
challenge, how diagnostics are shown.

Subclasses decide:
    ``SERVICE_TITLE``      window title
    ``build_tabs()``       the top tab bar (usually capability-gated)
    ``scope_for(tab_id)``  which backend scope a tab maps to
    ``build_service_menu()`` the first menu
    ``start_login()``      what "log in" means for this service
"""

from __future__ import annotations

import datetime
import time
from typing import Any, Dict, List, Tuple

import wx

from src.network.im_conversation import open_conversation
from src.network.im_call_ui import CallController
from src.network.im_web.base import (
    AUTH_CHALLENGE, AUTH_LOADING, AUTH_LOGGED_IN, AUTH_LOGGED_OUT, AUTH_PAIRING,
    AUTH_QR, CAP_VIDEO_CALL, CAP_VOICE_CALL,
    EV_AUTH_STATE, EV_CALL, EV_CHATS, EV_CHAT_UPDATED, EV_ERROR,
    EV_MESSAGE_NEW, EV_PRESENCE, EV_READY, EV_TYPING,
    CallState, Chat, Message,
)
from src.network.im_ui_common import (
    TabbedListFrame, _, apply_skin_tree, format_time, show_message, sounds,
    speak_notification, speak_titannet,
)
from src.titan_core.sound import play_sound

TAB_CALLS = 'calls'


class WebIMClientFrame(TabbedListFrame):
    """The list of conversations for one web-backed service."""

    SERVICE_TITLE = ''
    LIST_LABEL = ''

    def __init__(self, parent, backend):
        self.backend = backend
        self.call_log: List[CallState] = []
        self._pending_login = False
        # One login attempt produces both an auth_state push and a command
        # result, and each used to raise its own "show the page?" box. The
        # question is asked once per challenge, by whichever arrives first.
        self._page_question_asked = False
        self._pairing_code_shown = ''

        super().__init__(parent, title=self.SERVICE_TITLE or backend.SERVICE_LABEL)

        self.backend.add_listener(self._on_backend_event)
        self.calls = CallController(backend, lambda: self)
        self.build_menu()

        if sounds:
            try:
                sounds.welcome()
            except Exception:
                pass

        self._announce_auth(self.backend.auth, initial=True)
        if self.backend.logged_in:
            self.refresh()
        elif self.backend.ready:
            self.backend.refresh_auth_state()

    # ------------------------------------------------------------ to override
    def scope_for(self, tab_id: str) -> str:
        return tab_id

    def build_service_menu(self) -> Tuple[wx.Menu, str]:
        menu = wx.Menu()
        self.menu_bind(menu, _("Refresh\tF5"), self.refresh)
        self.menu_bind(menu, _("Search...\tCtrl+F"), self.search)
        menu.AppendSeparator()
        self.menu_bind(menu, _("Log in..."), self.start_login)
        self.menu_bind(menu, _("Log out"), self.log_out)
        menu.AppendSeparator()
        self.menu_bind(menu, _("Show the web page (advanced)"), self.show_web_page)
        self.menu_bind(menu, _("Connection diagnostics..."), self.show_diagnostics)
        menu.AppendSeparator()
        self.menu_bind(menu, _("Close\tEscape"), self.Close)
        return menu, _("&Service")

    def start_login(self) -> None:
        """Begin the service's login flow."""
        self.show_web_page()

    # ------------------------------------------------------------------ menus
    def build_menu(self) -> None:
        bar = wx.MenuBar()
        service_menu, service_label = self.build_service_menu()
        bar.Append(service_menu, service_label)

        conversation = wx.Menu()
        self.menu_bind(conversation, _("Open\tEnter"), self._activate_selected)
        self.menu_bind(conversation, _("Mark as read"), self._mark_read_selected)
        if self.backend.has(CAP_VOICE_CALL):
            self.menu_bind(conversation, _("Voice call\tCtrl+T"),
                           lambda: self._call_selected(False))
        if self.backend.has(CAP_VIDEO_CALL):
            self.menu_bind(conversation, _("Video call\tCtrl+Shift+T"),
                           lambda: self._call_selected(True))
        bar.Append(conversation, _("&Conversation"))

        self.SetMenuBar(bar)

    def menu_bind(self, menu: wx.Menu, label: str, handler) -> None:
        item = menu.Append(wx.ID_ANY, label)
        self.Bind(wx.EVT_MENU, lambda e: handler(), item)

    def build_toolbar(self, sizer: wx.BoxSizer) -> None:
        row = wx.BoxSizer(wx.HORIZONTAL)
        refresh = wx.Button(self.panel, label=_("Refresh"))
        refresh.Bind(wx.EVT_BUTTON, lambda e: self.refresh())
        row.Add(refresh, flag=wx.RIGHT, border=6)

        search = wx.Button(self.panel, label=_("Search"))
        search.Bind(wx.EVT_BUTTON, lambda e: self.search())
        row.Add(search, flag=wx.RIGHT, border=6)

        close = wx.Button(self.panel, label=_("Close"))
        close.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        row.Add(close)
        sizer.Add(row, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=8)

    # ------------------------------------------------------------------- rows
    def load_items(self, tab_id: str, background: bool = False) -> None:
        if tab_id == TAB_CALLS:
            self.apply_items(list(reversed(self.call_log)), tab_id,
                             background=background)
            return
        if not self.backend.logged_in:
            # Only say "nothing here" when there is genuinely nothing to show.
            # A session that is briefly re-checked must not wipe the list the
            # user is reading.
            if not self.items:
                self.apply_items([], tab_id, background=background)
            self.SetStatusText(self._auth_status_text())
            return
        self.backend.list_chats(
            scope=self.scope_for(tab_id),
            callback=lambda result: self._apply_chats(result, tab_id, background))

    def _apply_chats(self, result: Dict, tab_id: str,
                     background: bool = False) -> None:
        if not result.get('success'):
            if not background:
                # A background poll that fails is not worth interrupting for.
                speak_notification(result.get('error') or
                                   _("Could not load conversations"), 'error')
                self.apply_items([], tab_id)
            return

        chats = list(result.get('chats') or [])
        if (not chats and self.items and self.backend.logged_in
                and self.scope_for(tab_id) == 'all'):
            # A logged-in account whose full conversation list suddenly reads
            # empty is the page re-rendering, not an empty inbox. Keep what is
            # on screen. Filtered tabs (unread, groups) may legitimately empty
            # out, so they are still reported as they are.
            return
        self.apply_items(chats, tab_id, background=background)

    def format_row(self, item: Any) -> str:
        if isinstance(item, CallState):
            kind = _("Video call") if item.video else _("Voice call")
            direction = {
                'ringing_in': _("incoming"), 'ringing_out': _("outgoing"),
                'connected': _("answered"), 'ended': _("ended"),
            }.get(item.state, item.state)
            return _("{kind}, {peer}, {direction}, {time}").format(
                kind=kind, peer=item.peer or _("Unknown"), direction=direction,
                time=format_time(item.started_at or 0))

        if not isinstance(item, Chat):
            return str(item)

        parts = [item.name]
        if item.unread:
            parts.append(_("{n} unread").format(n=item.unread))
        if item.last_message:
            author = f"{item.last_author}: " if (item.is_group and item.last_author) else ''
            parts.append(f"{author}{item.last_message}")
        stamp = format_time(item.last_message_at)
        if stamp:
            parts.append(stamp)
        if item.online:
            parts.append(_("active now"))
        if item.muted:
            parts.append(_("muted"))
        return ', '.join(parts)

    def row_sound(self, item: Any, index: int) -> None:
        if isinstance(item, Chat) and item.unread:
            try:
                # The Titan-Net "unread replies" cue, the same one Titan-Net and
                # the Feedback Hub use for a row that still has something new.
                play_sound('titannet/newreplies.ogg')
            except Exception:
                pass

    def status_text(self) -> str:
        if not self.backend.logged_in:
            return self._auth_status_text()
        unread = sum(getattr(chat, 'unread', 0) or 0 for chat in self.items
                     if isinstance(chat, Chat))
        if unread:
            return _("{tab}: {n} conversations, {unread} unread").format(
                tab=self.tab_label(self.current_tab), n=len(self.items), unread=unread)
        return _("{tab}: {n} conversations").format(
            tab=self.tab_label(self.current_tab), n=len(self.items))

    def _auth_status_text(self) -> str:
        state = self.backend.auth.get('state')
        return {
            AUTH_LOADING: _("Connecting..."),
            AUTH_LOGGED_OUT: _("Not logged in"),
            AUTH_QR: _("Waiting for the login code"),
            AUTH_PAIRING: _("Waiting for device pairing"),
            AUTH_CHALLENGE: _("Additional confirmation required"),
        }.get(state, _("Connecting..."))

    # -------------------------------------------------------------- activation
    def activate(self, item: Any) -> None:
        if isinstance(item, CallState):
            if item.peer_id:
                self.backend.start_call(item.peer_id, video=item.video)
            return
        if isinstance(item, Chat):
            open_conversation(self, self.backend, item)

    def context_menu_items(self, item: Any):
        if not isinstance(item, Chat):
            return ()
        entries = [
            (_("Open"), self._activate_selected),
            (_("Mark as read"), self._mark_read_selected),
        ]
        if self.backend.has(CAP_VOICE_CALL):
            entries.append((_("Voice call"), lambda: self._call_selected(False)))
        if self.backend.has(CAP_VIDEO_CALL):
            entries.append((_("Video call"), lambda: self._call_selected(True)))
        return entries

    def _mark_read_selected(self) -> None:
        item = self.selected_item()
        if isinstance(item, Chat):
            self.backend.mark_read(item.id)
            speak_titannet(_("Marked as read"))
            self.refresh()

    def _call_selected(self, video: bool) -> None:
        item = self.selected_item()
        if not isinstance(item, Chat):
            return

        def _done(result: Dict) -> None:
            if not result.get('success'):
                speak_notification(result.get('error') or _("Cannot start the call"),
                                   'error')
                return
            if not result.get('confirmed'):
                # Pressed, but the page never showed a call starting.
                speak_notification(
                    _("The call was requested but the service has not started "
                      "it. Open the service page to see what happened."), 'error')
                return
            speak_titannet(_("Calling {name}").format(name=item.name))

        self.backend.start_call(item.id, video=video, callback=_done)

    # ------------------------------------------------------------------ tools
    def search(self) -> None:
        dialog = wx.TextEntryDialog(self, _("What are you looking for?"), _("Search"))
        apply_skin_tree(dialog)
        if dialog.ShowModal() == wx.ID_OK:
            query = dialog.GetValue().strip()
            if query:
                self.backend.search(query, callback=self._show_search_results)
        dialog.Destroy()

    def _show_search_results(self, result: Dict) -> None:
        if not result.get('success'):
            speak_notification(result.get('error') or _("Search failed"), 'error')
            return
        chats = result.get('chats') or []
        messages = result.get('messages') or []
        if not chats and not messages:
            speak_notification(_("Nothing found"), 'info')
            return
        self.apply_items(list(chats), self.current_tab, keep_focus=False)
        speak_titannet(_("Found {chats} conversations and {messages} messages").format(
            chats=len(chats), messages=len(messages)))

    def show_web_page(self) -> None:
        self.backend.show_page()
        speak_titannet(_("The service page is now on screen. Close it to return "
                         "to Titan; the connection stays up."))

    def show_diagnostics(self) -> None:
        def _done(result: Dict) -> None:
            if not result.get('success'):
                show_message(self, result.get('error') or _("Diagnostics unavailable"),
                             _("Diagnostics"), wx.OK | wx.ICON_ERROR)
                return
            lines = [
                _("Service: {service}").format(service=self.backend.SERVICE_LABEL),
                _("Address: {url}").format(url=result.get('href') or ''),
                _("Login state: {state}").format(
                    state=self.backend.auth.get('state', '?')),
                _("Capabilities: {caps}").format(
                    caps=', '.join(sorted(self.backend.capabilities)) or '-'),
                '',
                _("Data sources:"),
            ]
            for name, status in sorted((result.get('sources') or {}).items()):
                lines.append(f"  {name}: {status}")
            if self.backend.last_error:
                lines += ['', _("Last error: {error}").format(
                    error=self.backend.last_error)]
            # The page report is what says whether an empty conversation means
            # "no messages" or "this page no longer looks the way we read it".
            # A service that does not offer one simply contributes nothing.
            self.backend.dom_report(
                callback=lambda page: self._show_diagnostics_text(lines, page))

        self.backend.self_test(callback=_done)

    def _show_diagnostics_text(self, lines: List[str], page: Dict) -> None:
        if page.get('success'):
            lines += ['', _("Open conversation:")]
            for key in ('thread_id', 'thread_rows', 'thread_strategy',
                        'thread_root', 'conversation_rows', 'composer'):
                if key in page:
                    lines.append(f"  {key}: {page.get(key)}")
            for row in page.get('sample') or []:
                lines.append(f"  > {row}")
        show_message(self, '\n'.join(lines), _("Diagnostics"))

    def log_out(self) -> None:
        answer = show_message(
            self, _("Log out of {service}?").format(service=self.backend.SERVICE_LABEL),
            _("Log out"), wx.YES_NO | wx.ICON_QUESTION)
        if answer != wx.ID_YES:
            return

        def _done(result: Dict) -> None:
            if result.get('needs_page'):
                self.show_web_page()
                return
            speak_titannet(_("Logged out"))
            self.refresh()

        self.backend.logout(callback=_done)

    # ------------------------------------------------------------- lifecycle
    def on_escape(self) -> bool:
        return True

    def on_closed(self) -> None:
        self.backend.remove_listener(self._on_backend_event)
        try:
            self.calls.detach()
        except Exception:
            pass
        # The engine deliberately keeps running: buffers must keep filling and
        # notifications must keep arriving with the client window closed.

    # ----------------------------------------------------------- live events
    def _on_backend_event(self, event_type: str, payload: Any) -> None:
        if event_type == EV_READY:
            wx.CallAfter(self._on_ready)
            return
        if not isinstance(payload, dict):
            return

        if event_type == EV_AUTH_STATE:
            wx.CallAfter(self._announce_auth, payload, False)

        elif event_type == EV_CHATS:
            wx.CallAfter(self._on_chats_pushed, payload)

        elif event_type == EV_CHAT_UPDATED:
            wx.CallAfter(self._on_chat_updated, payload.get('chat'))

        elif event_type == EV_MESSAGE_NEW:
            wx.CallAfter(self._on_message, payload.get('message'))

        elif event_type == EV_TYPING:
            if payload.get('typing'):
                wx.CallAfter(self._on_typing, payload)

        elif event_type == EV_PRESENCE:
            wx.CallAfter(self._on_presence, payload.get('contact'))

        elif event_type == EV_CALL:
            call = payload.get('call')
            if isinstance(call, CallState) and call.state != 'idle':
                wx.CallAfter(self._on_call_logged, call)

        elif event_type == EV_ERROR:
            message = payload.get('message')
            if message:
                print(f"[{self.backend.SERVICE}] {message}")

    def _on_ready(self) -> None:
        if self._closing:
            return
        self.rebuild_tabs()
        self.build_menu()
        self.backend.refresh_auth_state()

    def _on_chats_pushed(self, payload: Dict) -> None:
        # The page pushes a snapshot whenever anything changes. That must never
        # be felt: it refreshes in the background, keeping the row the user is
        # reading and never grabbing focus.
        if self._closing or self.current_tab == TAB_CALLS:
            return
        if not self.backend.logged_in or payload.get('stale'):
            return
        self.refresh(background=True)

    def _on_chat_updated(self, chat) -> None:
        if self._closing or not isinstance(chat, Chat):
            return
        for row in range(1, self.listbox.GetCount()):
            data = self.listbox.GetClientData(row)
            if isinstance(data, Chat) and data.id == chat.id:
                self.listbox.SetString(row, self.format_row(chat))
                self.listbox.SetClientData(row, chat)
                position = row - 1
                if 0 <= position < len(self.items):
                    self.items[position] = chat
                break
        self.SetStatusText(self.status_text())

    def _on_message(self, message) -> None:
        if not isinstance(message, Message) or message.outgoing:
            return
        chat = self.backend.chats.get(message.chat_id)
        who = message.author or (chat.name if chat else _("Unknown"))
        body = message.text or ''

        # A conversation window that has this chat open announces it itself, so
        # the client only speaks for chats the user is not reading.
        from src.network.im_conversation import _open_windows
        if (self.backend.SERVICE, message.chat_id) in _open_windows:
            return

        if sounds:
            try:
                sounds.new_message()
            except Exception:
                pass
        speak_titannet(_("{service}, {who}: {text}").format(
            service=self.backend.SERVICE_LABEL, who=who, text=body))
        self._log_notification(who, body)

    def _log_notification(self, who: str, body: str) -> None:
        try:
            from src.ui.notificationcenter import add_notification
            now = datetime.datetime.now()
            add_notification(now.strftime('%Y-%m-%d'), now.strftime('%H:%M'),
                             self.backend.SERVICE_LABEL, f"{who}: {body}")
        except Exception as exc:
            print(f"[{self.backend.SERVICE}] notification center write failed: {exc}")

    def _on_typing(self, payload: Dict) -> None:
        # The conversation window plays its own typing cue, so a chat the user
        # is reading must not get two of them.
        from src.network.im_conversation import _open_windows
        if (self.backend.SERVICE, payload.get('chat_id')) in _open_windows:
            return
        if sounds:
            try:
                sounds.typing()
            except Exception:
                pass

    def _on_presence(self, contact) -> None:
        if contact is None or self._closing:
            return
        chat = self.backend.chats.get(getattr(contact, 'id', ''))
        if chat is not None:
            self._on_chat_updated(chat)

    def _on_call_logged(self, call: CallState) -> None:
        stamp = call.started_at or time.time()
        self.call_log.append(CallState(state=call.state, peer=call.peer,
                                       peer_id=call.peer_id, video=call.video,
                                       started_at=stamp))
        del self.call_log[:-100]
        if self.current_tab == TAB_CALLS:
            self.refresh(background=True)

    # -------------------------------------------------------------- auth flow
    def _announce_auth(self, auth: Dict, initial: bool) -> None:
        if self._closing:
            return
        state = (auth or {}).get('state')
        self.SetStatusText(self._auth_status_text())

        if state != AUTH_CHALLENGE:
            # A new challenge later on deserves its own question again.
            self._page_question_asked = False

        if state == AUTH_LOGGED_IN:
            self.rebuild_tabs()
            # Only the first load may place the focus; a session re-confirmed
            # later must not pull the user out of the row they are reading.
            self.refresh(background=not initial)
            if not initial:
                speak_notification(_("Connected to {service}").format(
                    service=self.backend.SERVICE_LABEL), 'success')
            return

        if state != AUTH_PAIRING:
            self._pairing_code_shown = ''

        if state == AUTH_PAIRING and auth.get('pairing_code'):
            self.announce_pairing_code(auth['pairing_code'])
            return

        if state == AUTH_CHALLENGE:
            self.ask_to_show_page(
                _("{service} needs an extra confirmation that cannot be "
                  "completed from Titan.\nShow the service page so you can "
                  "finish logging in?").format(service=self.backend.SERVICE_LABEL))
            return

        if state in (AUTH_LOGGED_OUT, AUTH_QR) and not self._pending_login:
            self._pending_login = True
            wx.CallAfter(self._offer_login)

    def ask_to_show_page(self, message: str) -> bool:
        """Ask once whether to bring the service page up, and do it on yes.

        Every route into a login problem - the auth push, the login command's
        result, a failed login - ends in the same question, so it is asked
        here and only once until the login state moves on. Returns True when
        the question was actually put to the user.
        """
        if self._closing or self._page_question_asked:
            return False
        if self.backend.page_visible:
            # The page is already up: there is nothing left to ask about.
            self._page_question_asked = True
            return False
        self._page_question_asked = True
        answer = show_message(self, message, _("Confirmation required"),
                              wx.YES_NO | wx.ICON_WARNING)
        if answer == wx.ID_YES:
            self.show_web_page()
        return True

    def _offer_login(self) -> None:
        self._pending_login = False
        if self._closing or self.backend.logged_in:
            return
        if self.backend.page_visible:
            # The user is logging in on the service page itself - a modal login
            # dialog on top of it would only get in the way.
            return
        self.start_login()

    def announce_pairing_code(self, code: str) -> bool:
        """Show a pairing code once, whichever route reported it first.

        The agent pushes the code as an auth state *and* returns it as the
        result of the pairing command; the user must still see one dialog.
        """
        if self._closing or not code or code == self._pairing_code_shown:
            return False
        self._pairing_code_shown = code
        self.show_pairing_code(code)
        return True

    def show_pairing_code(self, code: str) -> None:
        """Show a link-device code as text - the accessible alternative to a QR.

        Subclasses add the service's own instructions.
        """
        speak_titannet(_("Pairing code: {code}").format(code=' '.join(code)))
        show_message(self, _("Enter this code on your phone:\n\n{code}").format(code=code),
                     _("Pairing code"))
