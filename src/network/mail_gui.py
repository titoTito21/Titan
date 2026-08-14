# -*- coding: utf-8 -*-
"""Titan-Net Mail - the mailbox, the reader and the composer.

The mailbox behaves like every other Titan window: row 0 of the list is the tab
bar (Inbox / Unread / Sent), Left and Right cycle it, Enter opens, Escape goes
back one level before it closes, F5 refreshes, and every move plays the same
stereo-panned focus cue. That is not re-implemented here - the whole interaction
comes from ``im_ui_common.TabbedListFrame``, the same base the WhatsApp and
Messenger clients use, so the Mail client cannot drift away from the rest of
Titan.

A message opens as what it actually is. An HTML message opens as a **page** -
a real WebView2 document with its own headings, lists, tables and links, which
a screen reader browses exactly like a web page - never as markup and never as
Titan reading markup aloud. Nothing in that page may phone home: a strict
content policy blocks every remote fetch and every script, so opening a message
tells its sender nothing, and a link is followed only when the user says yes.

Everything else opens as the **reading list**: ``mail_format`` parses Markdown
or plain text into blocks and each block becomes one row - a heading announces
itself as a heading, a list item as a list item. Enter follows a link and
nothing more; the screen reader already reads the row, so Titan does not repeat
it. Ctrl+W moves between the two views, and the Links, Details and Source tabs
hold what would otherwise clutter the reading.

Composing offers the same three formats. Whatever the author picks, a readable
plain-text version is always what gets stored and sent as the message body; the
HTML alternative travels beside it, so a recipient using a normal mail client
sees the formatting and a recipient using Titan (or an old server) still reads
the message.
"""

from __future__ import annotations

import os
import threading
import time
import webbrowser
from typing import Any, Dict, List, Optional, Sequence, Tuple

import wx

from src.network import mail_format
from src.network.im_ui_common import (
    TabbedListFrame, _, apply_skin_tree, show_message,
    speak_notification, speak_titannet,
)
from src.settings.settings import get_setting, set_setting
from src.system import key_state
from src.titan_core.sound import play_sound

# Mail is a Titan-Net window like the Feedback Hub, so it sounds like one:
# the popup pair rather than the Titan IM window pair the shared base class
# plays for the messenger clients.
MAIL_OPEN_SOUND = 'ui/popup.ogg'
MAIL_CLOSE_SOUND = 'ui/popupclose.ogg'


def _play(name: str) -> None:
    try:
        play_sound(name)
    except Exception:
        pass


def _escape_pressed(event: wx.KeyEvent) -> bool:
    """True for a bare Escape - a Shift the input queue has latched aside.

    `wxKeyEvent` reads Shift out of this thread's input queue, and the Titan
    shell merges that queue with another program's every time it takes the
    foreground; a Shift held across that stays latched there.  Escape then
    arrives as Shift+Escape for ever and the window stops closing, which is
    not something the user can even see happening.  `key_state` asks the
    hardware instead.
    """
    if event.GetKeyCode() != wx.WXK_ESCAPE:
        return False
    return key_state.modifiers(event) & (wx.MOD_CONTROL | wx.MOD_ALT) == 0


TAB_INBOX = 'inbox'
TAB_UNREAD = 'unread'
TAB_SENT = 'sent'

TAB_MESSAGE = 'message'
TAB_LINKS = 'links'
TAB_DETAILS = 'details'
TAB_SOURCE = 'source'

# How often the open mailbox quietly asks the server whether anything arrived.
AUTO_REFRESH_MS = 90 * 1000


# --------------------------------------------------------------------------- #
# Row objects. The list holds real objects, not strings, so a row always knows
# what it is - which is what makes the context menus and Enter meaningful.
# --------------------------------------------------------------------------- #
class MailItem:
    """One message as the mailbox list shows it."""

    def __init__(self, data: Dict[str, Any], folder: str):
        self.data = data or {}
        self.folder = folder
        self.id = self.data.get('id', 0)

    @property
    def peer(self) -> str:
        """The address that matters in this folder: sender in, recipient out."""
        key = 'to_addr' if self.folder == TAB_SENT else 'from_addr'
        return (self.data.get(key) or '').strip()

    @property
    def subject(self) -> str:
        return (self.data.get('subject') or '').strip()

    @property
    def unread(self) -> bool:
        return self.folder != TAB_SENT and not self.data.get('read')

    @property
    def fmt(self) -> str:
        return mail_format.detect_format(self.data.get('body') or '',
                                         self.data.get('content_type') or '',
                                         self.data.get('body_html') or '')

    def when(self) -> str:
        stamp = (self.data.get('received_at') or '')[:16].replace('T', ' ')
        return stamp


class LinkRow:
    def __init__(self, label: str, url: str):
        self.label = label
        self.url = url
        self.id = url


class DetailRow:
    def __init__(self, label: str, value: str):
        self.label = label
        self.value = value
        self.id = label


class SourceRow:
    def __init__(self, index: int, text: str):
        self.index = index
        self.text = text
        self.id = f"line{index}"


# --------------------------------------------------------------------------- #
# Mailbox
# --------------------------------------------------------------------------- #
class MailFrame(TabbedListFrame):
    """The user's mailbox: username@domain, with folders as tabs."""

    VIEW_ID = 'titan_mail'
    LIST_LABEL = _("Messages:")
    # One earcon per close: the base class's Escape sound is blanked so the
    # closing one is the only thing heard, whichever way the window was left.
    ESCAPE_SOUND = ''
    CLOSE_SOUND = MAIL_CLOSE_SOUND

    def __init__(self, parent, titan_client):
        self.titan_client = titan_client
        self.address = ''
        self._folders: Dict[str, List[Dict[str, Any]]] = {TAB_INBOX: [], TAB_SENT: []}
        self._known_ids: Dict[str, set] = {TAB_INBOX: set(), TAB_SENT: set()}
        self._filter = ''
        self._first_load_done = False

        super().__init__(parent, title=_("Titan-Net Mail"), size=(920, 660))

        self._build_menu()
        try:
            from src.ui.window_switcher import register_window
            register_window(_("Titan-Net Mail"), window=self, category='messenger')
        except Exception:
            pass

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self._poll(), self._timer)
        self._timer.Start(AUTO_REFRESH_MS)

        _play(MAIL_OPEN_SOUND)
        self.refresh()

    # ------------------------------------------------------------------ setup
    def build_tabs(self) -> Sequence[Tuple[str, str]]:
        return [
            (TAB_INBOX, _("Inbox")),
            (TAB_UNREAD, _("Unread")),
            (TAB_SENT, _("Sent")),
        ]

    def build_toolbar(self, sizer: wx.BoxSizer) -> None:
        self.address_label = wx.StaticText(
            self.panel, label=_("Your address: loading..."))
        sizer.Add(self.address_label, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=8)

    def build_footer(self, sizer: wx.BoxSizer) -> None:
        row = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in (
            (_("Open"), lambda: self._open_selected()),
            (_("Compose"), self._compose),
            (_("Reply"), self._reply_selected),
            (_("Delete"), self._delete_selected),
            (_("Refresh"), lambda: self.refresh()),
            (_("Close"), self.Close),
        ):
            button = wx.Button(self.panel, label=label)
            button.Bind(wx.EVT_BUTTON, lambda e, h=handler: h())
            row.Add(button, flag=wx.RIGHT, border=6)
        sizer.Add(row, flag=wx.ALL, border=8)

    def _build_menu(self) -> None:
        bar = wx.MenuBar()

        mailbox = wx.Menu()
        self._menu_bind(mailbox, _("Compose\tCtrl+N"), self._compose)
        self._menu_bind(mailbox, _("Refresh\tF5"), self.refresh)
        self._menu_bind(mailbox, _("Search...\tCtrl+F"), self._search)
        self._menu_bind(mailbox, _("Clear search\tCtrl+Shift+F"), self._clear_search)
        mailbox.AppendSeparator()
        self._menu_bind(mailbox, _("Copy my address"), self._copy_address)
        self._menu_bind(mailbox, _("Close\tEscape"), self.Close)
        bar.Append(mailbox, _("&Mailbox"))

        message = wx.Menu()
        self._menu_bind(message, _("Open\tEnter"), self._open_selected)
        self._menu_bind(message, _("Reply\tCtrl+R"), self._reply_selected)
        self._menu_bind(message, _("Forward\tCtrl+Shift+R"), self._forward_selected)
        self._menu_bind(message, _("Copy sender address"), self._copy_peer)
        self._menu_bind(message, _("Delete\tDelete"), self._delete_selected)
        bar.Append(message, _("&Message"))

        self.SetMenuBar(bar)

    def _menu_bind(self, menu: wx.Menu, label: str, handler) -> None:
        item = menu.Append(wx.ID_ANY, label)
        self.Bind(wx.EVT_MENU, lambda e: handler(), item)

    # ------------------------------------------------------------------- rows
    def load_items(self, tab_id: str, background: bool = False) -> None:
        folder = TAB_SENT if tab_id == TAB_SENT else TAB_INBOX
        if self._folders[folder] or background:
            # Show what is already known immediately; the fetch below refreshes
            # it underneath without moving the user.
            self.apply_items(self._rows(tab_id), tab_id, background=background)

        def _fetch():
            result = self.titan_client.get_mailbox(folder)
            wx.CallAfter(self._apply_folder, result, folder, tab_id, background)

        threading.Thread(target=_fetch, daemon=True).start()

    def _apply_folder(self, result: Dict[str, Any], folder: str, tab_id: str,
                      background: bool) -> None:
        if not result.get('success'):
            if not background:
                play_sound('core/error.ogg')
                speak_notification(result.get('error') or _("Could not load mail"),
                                   'error')
                self.apply_items(self._rows(tab_id), tab_id)
            return

        self.address = result.get('address') or self.address
        self.address_label.SetLabel(
            _("Your address: {address}").format(address=self.address))

        messages = list(result.get('messages') or [])
        arrived = self._new_arrivals(folder, messages)
        self._folders[folder] = messages
        self._known_ids[folder] = {m.get('id') for m in messages}

        self.apply_items(self._rows(tab_id), tab_id, background=background)
        if arrived:
            self._announce_arrivals(arrived)
        self._first_load_done = True

    def _new_arrivals(self, folder: str, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Inbox messages seen for the first time since this window opened."""
        if folder != TAB_INBOX or not self._first_load_done:
            return []
        known = self._known_ids.get(folder) or set()
        return [m for m in messages if m.get('id') not in known]

    def _announce_arrivals(self, arrived: List[Dict[str, Any]]) -> None:
        if len(arrived) == 1:
            item = MailItem(arrived[0], TAB_INBOX)
            text = _("New mail from {who}: {subject}").format(
                who=item.peer or _("unknown sender"),
                subject=item.subject or _("(no subject)"))
        else:
            text = _("{n} new messages").format(n=len(arrived))
        try:
            play_sound('titannet/message.ogg')
        except Exception:
            pass
        speak_notification(text, 'info')
        self._push_to_buffers(arrived)

    def _push_to_buffers(self, arrived: List[Dict[str, Any]]) -> None:
        """File new mail in the Titan Buffer System, under Titan-Net.

        The mailbox is only polled while this window is open, so the buffer
        holds what arrived during the session - it is a review list, not a
        second copy of the mailbox.
        """
        try:
            from src.buffers import buffer_bus
        except Exception:
            return
        for data in arrived:
            item = MailItem(data, TAB_INBOX)
            try:
                buffer_bus.push(
                    'titannet', 'mail',
                    _("{subject} - from {who}").format(
                        subject=item.subject or _("(no subject)"),
                        who=item.peer),
                    author=item.peer, kind='message',
                    category_name=_("Titan-Net"), buffer_name=_("Mail"))
            except Exception:
                return

    def _rows(self, tab_id: str) -> List[MailItem]:
        folder = TAB_SENT if tab_id == TAB_SENT else TAB_INBOX
        items = [MailItem(data, folder) for data in self._folders[folder]]
        if tab_id == TAB_UNREAD:
            items = [item for item in items if item.unread]
        if self._filter:
            needle = self._filter.lower()
            items = [item for item in items
                     if needle in item.subject.lower() or needle in item.peer.lower()]
        return items

    def format_row(self, item: Any) -> str:
        if not isinstance(item, MailItem):
            return str(item)
        parts = []
        if item.unread:
            parts.append(_("unread"))
        parts.append(item.peer or _("unknown sender"))
        parts.append(item.subject or _("(no subject)"))
        parts.append(item.when())
        if item.fmt != mail_format.FORMAT_PLAIN:
            parts.append(mail_format.format_label(item.fmt))
        return ', '.join(part for part in parts if part)

    def row_sound(self, item: Any, index: int) -> None:
        if isinstance(item, MailItem) and item.unread:
            try:
                play_sound('ui/focus_expanded.ogg')
            except Exception:
                pass

    def status_text(self) -> str:
        base = _("{tab}: {n} messages").format(
            tab=self.tab_label(self.current_tab), n=len(self.items))
        if self._filter:
            base += ', ' + _("search: {text}").format(text=self._filter)
        return base

    # ------------------------------------------------------------- activation
    def activate(self, item: Any) -> None:
        self._open(item)

    def context_menu_items(self, item: Any):
        if not isinstance(item, MailItem):
            return ()
        return (
            (_("Open"), lambda: self._open(item)),
            (_("Reply"), lambda: self._reply(item)),
            (_("Forward"), lambda: self._forward(item)),
            (_("Copy sender address"), lambda: self._copy(item.peer)),
            (_("Delete"), lambda: self._delete(item)),
        )

    def extra_key(self, keycode: int, modifiers: int, item: Optional[Any]) -> bool:
        if keycode == wx.WXK_DELETE and modifiers == wx.MOD_NONE and item is not None:
            self._delete(item)
            return True
        if keycode == ord('N') and modifiers == wx.MOD_CONTROL:
            self._compose()
            return True
        if keycode == ord('F') and modifiers == wx.MOD_CONTROL:
            self._search()
            return True
        if keycode == ord('F') and modifiers == (wx.MOD_CONTROL | wx.MOD_SHIFT):
            self._clear_search()
            return True
        if keycode == ord('R') and modifiers == wx.MOD_CONTROL and item is not None:
            self._reply(item)
            return True
        if keycode == ord('R') and modifiers == (wx.MOD_CONTROL | wx.MOD_SHIFT) \
                and item is not None:
            self._forward(item)
            return True
        return False

    def on_escape(self) -> bool:
        if self._filter:
            # Escape peels one level: the search first, the window after.
            self._clear_search()
            return False
        return True

    def on_closed(self) -> None:
        try:
            self._timer.Stop()
        except Exception:
            pass
        try:
            from src.ui.window_switcher import unregister_window
            unregister_window(_("Titan-Net Mail"))
        except Exception:
            pass

    # ---------------------------------------------------------------- actions
    def _poll(self) -> None:
        if not self.IsShown():
            return
        self.refresh(background=True)

    def _selected(self) -> Optional[MailItem]:
        item = self.selected_item()
        return item if isinstance(item, MailItem) else None

    def _open_selected(self) -> None:
        item = self._selected()
        if item:
            self._open(item)

    def _reply_selected(self) -> None:
        item = self._selected()
        if item:
            self._reply(item)

    def _forward_selected(self) -> None:
        item = self._selected()
        if item:
            self._forward(item)

    def _delete_selected(self) -> None:
        item = self._selected()
        if item:
            self._delete(item)

    def _copy_peer(self) -> None:
        item = self._selected()
        if item:
            self._copy(item.peer)

    def _copy_address(self) -> None:
        self._copy(self.address)

    def _copy(self, text: str) -> None:
        if not text:
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Close()
            speak_titannet(_("Copied: {text}").format(text=text))

    def _open(self, item: MailItem) -> None:
        speak_titannet(_("Opening the message..."))

        def _fetch():
            result = self.titan_client.get_mail(item.id)
            wx.CallAfter(self._show, result, item)

        threading.Thread(target=_fetch, daemon=True).start()

    def _show(self, result: Dict[str, Any], item: MailItem) -> None:
        if not result.get('success'):
            play_sound('core/error.ogg')
            speak_notification(result.get('error') or _("Could not open the message"),
                               'error')
            return
        message = result.get('message') or {}
        # An HTML message opens as a page, everything else as the reading list.
        open_message(self, self.titan_client, message, item.folder)
        # Reading clears the unread marker server-side; mirror that here so the
        # list does not keep saying "unread" until the next poll.
        item.data['read'] = 1
        for data in self._folders[item.folder]:
            if data.get('id') == item.id:
                data['read'] = 1
        self.refresh(background=True)

    def _reply(self, item: MailItem) -> None:
        def _fetch():
            result = self.titan_client.get_mail(item.id)
            wx.CallAfter(lambda: self._compose_reply(result))

        threading.Thread(target=_fetch, daemon=True).start()

    def _compose_reply(self, result: Dict[str, Any], forward: bool = False) -> None:
        if not result.get('success'):
            play_sound('core/error.ogg')
            speak_notification(result.get('error') or _("Could not open the message"),
                               'error')
            return
        open_compose(self, self.titan_client, result.get('message') or {},
                     forward=forward, on_sent=lambda: self.refresh())

    def _forward(self, item: MailItem) -> None:
        def _fetch():
            result = self.titan_client.get_mail(item.id)
            wx.CallAfter(lambda: self._compose_reply(result, forward=True))

        threading.Thread(target=_fetch, daemon=True).start()

    def _compose(self) -> None:
        open_composer(self, self.titan_client, on_sent=lambda: self.refresh())

    def _delete(self, item: MailItem) -> None:
        answer = show_message(
            self,
            _("Delete this message?\n\n{subject}").format(
                subject=item.subject or _("(no subject)")),
            _("Titan-Net Mail"), wx.YES_NO | wx.ICON_QUESTION)
        if answer != wx.ID_YES:
            return

        def _do():
            result = self.titan_client.delete_mail(item.id)
            wx.CallAfter(self._deleted, result, item)

        threading.Thread(target=_do, daemon=True).start()

    def _deleted(self, result: Dict[str, Any], item: MailItem) -> None:
        if not result.get('success'):
            play_sound('core/error.ogg')
            speak_notification(result.get('error') or _("Could not delete the message"),
                               'error')
            return
        speak_titannet(_("Message deleted"))
        self._folders[item.folder] = [data for data in self._folders[item.folder]
                                      if data.get('id') != item.id]
        self._known_ids[item.folder].discard(item.id)
        self.apply_items(self._rows(self.current_tab), self.current_tab,
                         keep_focus=True)

    def _search(self) -> None:
        dialog = wx.TextEntryDialog(
            self, _("Show only messages whose sender or subject contains:"),
            _("Search mail"), self._filter)
        apply_skin_tree(dialog)
        if dialog.ShowModal() == wx.ID_OK:
            self._filter = dialog.GetValue().strip()
            self.apply_items(self._rows(self.current_tab), self.current_tab)
            speak_titannet(self.status_text())
        dialog.Destroy()

    def _clear_search(self) -> None:
        if not self._filter:
            return
        self._filter = ''
        self.apply_items(self._rows(self.current_tab), self.current_tab)
        speak_titannet(_("Search cleared"))


# --------------------------------------------------------------------------- #
# The page view: an HTML message shown as the page it is
# --------------------------------------------------------------------------- #
# Nothing may leave this window. A mail body is markup written by a stranger,
# and a browser that fetches what it references announces to the sender that
# the message was opened (and when, and from where). The policy below lets a
# message use its own layout and inline styling, and blocks every remote fetch
# and every script: no tracking pixel, no web font, no code.
MAIL_CSP = ("default-src 'none'; img-src data: cid:; style-src 'unsafe-inline'; "
            "font-src data:; form-action 'none'; frame-src 'none'; script-src 'none'")

_CSP_TAG = ('<meta http-equiv="Content-Security-Policy" content="' + MAIL_CSP + '">'
            '<meta name="referrer" content="no-referrer">')


def page_view_available() -> bool:
    """Whether this machine can show a message as a rendered page."""
    try:
        # Aliased on purpose: a plain ``import wx.html2`` binds the name ``wx``
        # locally, which shadows the module-level wx for the rest of the scope.
        import wx.html2 as html2
        return bool(html2.WebView.IsBackendAvailable(html2.WebViewBackendEdge)
                    or html2.WebView.IsBackendAvailable(html2.WebViewBackendDefault))
    except Exception:
        return False


def _sealed_document(html: str, title: str) -> str:
    """The message's own HTML, with the fetch policy put in front of it."""
    head = f'<head><meta charset="utf-8"><title>{title}</title>{_CSP_TAG}</head>'
    lowered = html.lower()
    if '<head' in lowered:
        # Insert straight after the opening <head ...> so the policy is the
        # first thing the renderer sees.
        start = lowered.index('<head')
        end = html.index('>', start) + 1
        return html[:end] + _CSP_TAG + html[end:]
    if '<html' in lowered:
        start = lowered.index('<html')
        end = html.index('>', start) + 1
        return html[:end] + head + html[end:]
    return f'<!DOCTYPE html><html>{head}<body>{html}</body></html>'


class MailPageFrame(wx.Frame):
    """An HTML message rendered as a page, the way its sender wrote it.

    The document is real - a WebView2 document with its own headings, lists,
    tables and links - so a screen reader browses it exactly like a web page,
    with the reading cursor, headings navigation and everything else it already
    knows how to do. Titan does not speak over it; the page speaks for itself.

    Ctrl+M switches to the reading list for the same message, which is the
    better tool for a wall of text or a menu of links.
    """

    def __init__(self, parent, titan_client, message: Dict[str, Any],
                 folder: str = TAB_INBOX):
        self.titan_client = titan_client
        self.message = message or {}
        self.folder = folder
        subject = (self.message.get('subject') or '').strip() or _("(no subject)")
        super().__init__(parent, title=subject, size=(980, 720))

        panel = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)
        self.header = wx.StaticText(panel, label=_("From {who}, {when}").format(
            who=(self.message.get('from_addr') or '').strip() or _("unknown sender"),
            when=(self.message.get('received_at') or '')[:16].replace('T', ' ')))
        box.Add(self.header, flag=wx.ALL, border=8)

        # Aliased: ``import wx.html2`` would make ``wx`` a local name here and
        # break every wx.* use in this constructor.
        import wx.html2 as html2
        self.webview = html2.WebView.New(panel)
        box.Add(self.webview, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)
        panel.SetSizer(box)

        self.CreateStatusBar()
        self.SetStatusText(_("Page view. Ctrl+W for the reading list."))
        self._build_menu()

        self.webview.Bind(html2.EVT_WEBVIEW_NAVIGATING, self._on_navigating)
        self.webview.Bind(html2.EVT_WEBVIEW_NEWWINDOW, self._on_new_window)
        self.webview.Bind(html2.EVT_WEBVIEW_LOADED, self._on_loaded)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        apply_skin_tree(self)
        try:
            from src.ui.window_switcher import register_window
            register_window(subject, window=self, category='messenger')
        except Exception:
            pass
        self._window_name = subject

        _play(MAIL_OPEN_SOUND)
        self._loaded = False
        html = self.message.get('body_html') or self.message.get('body') or ''
        self.webview.SetPage(_sealed_document(html, subject), '')

    def _build_menu(self) -> None:
        bar = wx.MenuBar()
        message = wx.Menu()
        self._menu_bind(message, _("Reading list\tCtrl+W"), self._open_list)
        self._menu_bind(message, _("Reply\tCtrl+R"), self._reply)
        self._menu_bind(message, _("Forward\tCtrl+Shift+R"), self._forward)
        message.AppendSeparator()
        self._menu_bind(message, _("Open in web browser\tCtrl+B"), self._open_external)
        self._menu_bind(message, _("Close\tEscape"), self.Close)
        bar.Append(message, _("&Message"))
        self.SetMenuBar(bar)

    def _menu_bind(self, menu: wx.Menu, label: str, handler) -> None:
        item = menu.Append(wx.ID_ANY, label)
        self.Bind(wx.EVT_MENU, lambda e: handler(), item)

    # ------------------------------------------------------------------ events
    def _on_loaded(self, event) -> None:
        self._loaded = True
        # Put the reading cursor inside the document, not on the frame.
        try:
            self.webview.SetFocus()
        except Exception:
            pass
        event.Skip()

    def _on_navigating(self, event) -> None:
        """The page never navigates. A link the user follows is a real link."""
        url = event.GetURL() or ''
        if not self._loaded or url.startswith('about:'):
            return  # the message itself being put on screen
        event.Veto()
        open_url_with_confirmation(self, url)

    def _on_new_window(self, event) -> None:
        event.Veto()
        open_url_with_confirmation(self, event.GetURL() or '')

    def _on_key(self, event) -> None:
        keycode, modifiers = event.GetKeyCode(), event.GetModifiers()
        if _escape_pressed(event):
            self.Close()
            return
        if keycode == ord('W') and modifiers == wx.MOD_CONTROL:
            self._open_list()
            return
        if keycode == ord('R') and modifiers == wx.MOD_CONTROL:
            self._reply()
            return
        if keycode == ord('R') and modifiers == (wx.MOD_CONTROL | wx.MOD_SHIFT):
            self._forward()
            return
        if keycode == ord('B') and modifiers == wx.MOD_CONTROL:
            self._open_external()
            return
        event.Skip()

    def _on_close(self, event) -> None:
        try:
            # Stop the document before the frame goes. A WebView2 that is still
            # loading when its window is torn down can take the process with it,
            # and the destruction itself is left to wx - doing both by hand is
            # what turns one teardown into two.
            self.webview.Stop()
        except Exception:
            pass
        try:
            from src.ui.window_switcher import unregister_window
            unregister_window(self._window_name)
        except Exception:
            pass
        _play(MAIL_CLOSE_SOUND)
        event.Skip()

    # ----------------------------------------------------------------- actions
    def _open_list(self) -> None:
        frame = MailMessageFrame(self.GetParent(), self.titan_client, self.message,
                                 self.folder)
        frame.Show()
        frame.listbox.SetFocus()
        self.Close()

    def _reply(self) -> None:
        open_compose(self, self.titan_client, self.message, forward=False)

    def _forward(self) -> None:
        open_compose(self, self.titan_client, self.message, forward=True)

    def _open_external(self) -> None:
        open_in_external_browser(self, self.message)


def open_url_with_confirmation(parent, url: str) -> None:
    """Open a link from a message in the user's browser, once they agree."""
    url = mail_format.absolute_url(url)
    if not url:
        return
    answer = show_message(
        parent, _("Open this address in your web browser?\n\n{url}").format(url=url),
        _("Titan-Net Mail"), wx.YES_NO | wx.ICON_QUESTION)
    if answer != wx.ID_YES:
        return
    try:
        webbrowser.open(url)
        speak_titannet(_("Opening in your browser"))
    except Exception as exc:
        print(f"[Mail] could not open {url}: {exc}")
        speak_notification(_("Could not open the address"), 'error')


def open_in_external_browser(parent, message: Dict[str, Any]) -> None:
    """Write the message to a temporary file and hand it to the real browser.

    For the times Titan's own page view is not the point - showing the message
    to somebody else, printing it, checking how it looks outside Titan.
    """
    html = message.get('body_html') or message.get('body') or ''
    if not html:
        return
    try:
        import tempfile
        subject = (message.get('subject') or '').strip() or _("(no subject)")
        handle = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False,
                                             encoding='utf-8')
        handle.write(_sealed_document(html, subject))
        handle.close()
        webbrowser.open('file:///' + handle.name.replace('\\', '/'))
        speak_titannet(_("Opening in your browser"))
    except Exception as exc:
        print(f"[Mail] could not open the message in a browser: {exc}")
        speak_notification(_("Could not open the message in a browser"), 'error')


def open_message(parent, titan_client, message: Dict[str, Any],
                 folder: str = TAB_INBOX, as_page: Optional[bool] = None):
    """Open one message the way its content deserves.

    An HTML message opens as a page - that is what it was written as - and
    everything else opens as the reading list. Either view switches to the
    other with Ctrl+M, and the list is also what a machine without WebView2
    falls back to.
    """
    rendered_format = mail_format.detect_format(message.get('body') or '',
                                                message.get('content_type') or '',
                                                message.get('body_html') or '')
    if as_page is None:
        as_page = rendered_format == mail_format.FORMAT_HTML
    if as_page and page_view_available():
        try:
            frame = MailPageFrame(parent, titan_client, message, folder)
            frame.Show()
            return frame
        except Exception as exc:
            print(f"[Mail] page view unavailable, falling back to the list: {exc}")
    frame = MailMessageFrame(parent, titan_client, message, folder)
    frame.Show()
    frame.listbox.SetFocus()
    return frame


# --------------------------------------------------------------------------- #
# Reader
# --------------------------------------------------------------------------- #
class MailMessageFrame(TabbedListFrame):
    """One message: its body as navigable rows, plus links, details and source."""

    VIEW_ID = 'titan_mail_message'
    LIST_LABEL = _("Message:")
    ESCAPE_SOUND = ''
    CLOSE_SOUND = MAIL_CLOSE_SOUND

    def __init__(self, parent, titan_client, message: Dict[str, Any],
                 folder: str = TAB_INBOX):
        self.titan_client = titan_client
        self.message = message or {}
        self.folder = folder
        self.rendered = mail_format.render(
            self.message.get('body') or '',
            self.message.get('content_type') or '',
            self.message.get('body_html') or '')
        self._show_quoted = True

        subject = (self.message.get('subject') or '').strip() or _("(no subject)")
        super().__init__(parent, title=subject, size=(920, 660))

        self._build_menu()
        self.header.SetLabel(self._header_text())
        _play(MAIL_OPEN_SOUND)
        self.refresh()

    def _header_text(self) -> str:
        who = (self.message.get('from_addr') or '').strip()
        return _("From {who}, {when}, {format}").format(
            who=who or _("unknown sender"),
            when=(self.message.get('received_at') or '')[:16].replace('T', ' '),
            format=mail_format.format_label(self.rendered.fmt))

    def build_tabs(self) -> Sequence[Tuple[str, str]]:
        tabs = [(TAB_MESSAGE, _("Message"))]
        if self.rendered.links:
            tabs.append((TAB_LINKS, _("Links")))
        tabs.append((TAB_DETAILS, _("Details")))
        tabs.append((TAB_SOURCE, _("Source")))
        return tabs

    def _build_menu(self) -> None:
        bar = wx.MenuBar()

        message = wx.Menu()
        self._menu_bind(message, _("Reply\tCtrl+R"), self._reply)
        self._menu_bind(message, _("Forward\tCtrl+Shift+R"), self._forward)
        self._menu_bind(message, _("Read whole message\tCtrl+Shift+M"), self._read_all)
        self._menu_bind(message, _("Copy whole message\tCtrl+Shift+C"), self._copy_all)
        self._menu_bind(message, _("Save to file...\tCtrl+S"), self._save)
        message.AppendSeparator()
        self._menu_bind(message, _("Delete\tDelete"), self._delete)
        self._menu_bind(message, _("Close\tEscape"), self.Close)
        bar.Append(message, _("&Message"))

        view = wx.Menu()
        self._menu_bind(view, _("Read this line\tCtrl+M"), self._read_row)
        self._menu_bind(view, _("Copy this line\tCtrl+C"), self._copy_row)
        self._menu_bind(view, _("Open link\tCtrl+L"), self._open_link)
        self._menu_bind(view, _("Show quoted text\tCtrl+Q"), self._toggle_quoted)
        if self.rendered.fmt == mail_format.FORMAT_HTML:
            if page_view_available():
                self._menu_bind(view, _("Show as a web page\tCtrl+W"), self._open_page)
            self._menu_bind(view, _("Open in web browser\tCtrl+B"), self._open_in_browser)
        bar.Append(view, _("&View"))

        self.SetMenuBar(bar)

    def _menu_bind(self, menu: wx.Menu, label: str, handler) -> None:
        item = menu.Append(wx.ID_ANY, label)
        self.Bind(wx.EVT_MENU, lambda e: handler(), item)

    # ------------------------------------------------------------------- rows
    def load_items(self, tab_id: str, background: bool = False) -> None:
        self.apply_items(self._rows(tab_id), tab_id, background=background)

    def _rows(self, tab_id: str) -> List[Any]:
        if tab_id == TAB_LINKS:
            return [LinkRow(label, url) for label, url in self.rendered.links]
        if tab_id == TAB_DETAILS:
            return self._details()
        if tab_id == TAB_SOURCE:
            source = self.message.get('body_html') or self.message.get('body') or ''
            lines = source.replace('\r\n', '\n').replace('\r', '\n').split('\n')
            return [SourceRow(index, line) for index, line in enumerate(lines)
                    if line.strip()]
        blocks = self.rendered.blocks
        if not self._show_quoted:
            blocks = [block for block in blocks
                      if block.kind != mail_format.KIND_QUOTE]
        return list(blocks)

    def _details(self) -> List[DetailRow]:
        message = self.message
        rows = [
            DetailRow(_("From"), message.get('from_addr') or ''),
            DetailRow(_("To"), message.get('to_addr') or ''),
            DetailRow(_("Subject"), message.get('subject') or _("(no subject)")),
            DetailRow(_("Date"), (message.get('received_at') or '').replace('T', ' ')),
            DetailRow(_("Format"), mail_format.format_label(self.rendered.fmt)),
            DetailRow(_("Folder"), _("Sent") if self.folder == TAB_SENT else _("Inbox")),
            DetailRow(_("Lines"), str(len(self.rendered.blocks))),
            DetailRow(_("Links"), str(len(self.rendered.links))),
        ]
        if self.rendered.images:
            rows.append(DetailRow(_("Images"), str(len(self.rendered.images))))
        if message.get('message_id'):
            rows.append(DetailRow(_("Message identifier"), message['message_id']))
        if message.get('in_reply_to'):
            rows.append(DetailRow(_("In reply to"), message['in_reply_to']))
        return rows

    def format_row(self, item: Any) -> str:
        if isinstance(item, LinkRow):
            if item.label and item.label != item.url:
                return _("{label}: {url}").format(label=item.label, url=item.url)
            return item.url
        if isinstance(item, DetailRow):
            return f"{item.label}: {item.value}"
        if isinstance(item, SourceRow):
            return item.text
        if isinstance(item, mail_format.Block):
            text = item.speak()
            if item.links and item.kind != mail_format.KIND_PARAGRAPH:
                return text
            if item.links:
                return _("{text} (contains a link)").format(text=text)
            return text
        return str(item)

    def row_key(self, item: Any) -> str:
        value = getattr(item, 'id', None)
        return f"id:{value}" if value else ''

    def status_text(self) -> str:
        return _("{tab}: {n} entries, {format}").format(
            tab=self.tab_label(self.current_tab), n=len(self.items),
            format=mail_format.format_label(self.rendered.fmt))

    # ------------------------------------------------------------- activation
    def activate(self, item: Any) -> None:
        # Enter follows a link and nothing else. The screen reader already reads
        # the row the user is on - speaking it again on Enter would only repeat
        # what they just heard. Ctrl+M is there for when they do want it said.
        url = self._row_url(item)
        if url:
            self._open_url(url)
            return
        if self.rendered.fmt == mail_format.FORMAT_HTML and page_view_available():
            # A row of an HTML message that is not a link: the page itself is
            # the more useful answer to "open this".
            self._open_page()

    def context_menu_items(self, item: Any):
        entries = [(_("Read this line"), self._read_row),
                   (_("Copy this line"), self._copy_row)]
        url = self._row_url(item)
        if url:
            entries.insert(0, (_("Open link"), lambda: self._open_url(url)))
            entries.append((_("Copy link"), lambda: self._copy(url)))
        entries.append((_("Reply"), self._reply))
        return entries

    def extra_key(self, keycode: int, modifiers: int, item: Optional[Any]) -> bool:
        if keycode == ord('R') and modifiers == wx.MOD_CONTROL:
            self._reply()
            return True
        if keycode == ord('R') and modifiers == (wx.MOD_CONTROL | wx.MOD_SHIFT):
            self._forward()
            return True
        if keycode == ord('M') and modifiers == wx.MOD_CONTROL:
            self._read_row()
            return True
        if keycode == ord('M') and modifiers == (wx.MOD_CONTROL | wx.MOD_SHIFT):
            self._read_all()
            return True
        if keycode == ord('C') and modifiers == wx.MOD_CONTROL:
            self._copy_row()
            return True
        if keycode == ord('C') and modifiers == (wx.MOD_CONTROL | wx.MOD_SHIFT):
            self._copy_all()
            return True
        if keycode == ord('L') and modifiers == wx.MOD_CONTROL:
            self._open_link()
            return True
        if keycode == ord('Q') and modifiers == wx.MOD_CONTROL:
            self._toggle_quoted()
            return True
        if keycode == ord('B') and modifiers == wx.MOD_CONTROL:
            self._open_in_browser()
            return True
        if keycode == ord('S') and modifiers == wx.MOD_CONTROL:
            self._save()
            return True
        if keycode == wx.WXK_DELETE and modifiers == wx.MOD_NONE:
            self._delete()
            return True
        return False

    # ---------------------------------------------------------------- actions
    def _row_url(self, item: Any) -> str:
        if isinstance(item, LinkRow):
            return item.url
        if isinstance(item, mail_format.Block):
            return item.url
        return ''

    def _row_text(self, item: Any) -> str:
        if isinstance(item, mail_format.Block):
            return item.plain()
        if isinstance(item, LinkRow):
            return item.url
        if isinstance(item, DetailRow):
            return f"{item.label}: {item.value}"
        if isinstance(item, SourceRow):
            return item.text
        return '' if item is None else str(item)

    def _read_row(self) -> None:
        text = self._row_text(self.selected_item())
        if text:
            speak_titannet(text)

    def _read_all(self) -> None:
        speak_titannet(self.rendered.speech() or _("This message has no text"))

    def _copy_row(self) -> None:
        self._copy(self._row_text(self.selected_item()))

    def _copy_all(self) -> None:
        self._copy(self.rendered.text())

    def _copy(self, text: str) -> None:
        if not text:
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Close()
            speak_titannet(_("Copied"))

    def _open_link(self) -> None:
        url = self._row_url(self.selected_item())
        if url:
            self._open_url(url)
            return
        if self.rendered.links:
            self.current_tab = TAB_LINKS
            self.refresh()
            speak_titannet(_("This line has no link. Showing the message's links."))
            return
        speak_titannet(_("This message has no links"))

    def _open_url(self, url: str) -> None:
        open_url_with_confirmation(self, url)

    def _open_page(self) -> None:
        """Switch to the page view - the message as the page it was written as."""
        if not page_view_available():
            speak_notification(_("The page view is not available on this computer"),
                               'warning')
            return
        try:
            frame = MailPageFrame(self.GetParent(), self.titan_client, self.message,
                                  self.folder)
            frame.Show()
            self.Close()
        except Exception as exc:
            print(f"[Mail] could not open the page view: {exc}")
            speak_notification(_("Could not show the message as a page"), 'error')

    def _toggle_quoted(self) -> None:
        self._show_quoted = not self._show_quoted
        speak_titannet(_("Quoted text shown") if self._show_quoted
                       else _("Quoted text hidden"))
        self.refresh()

    def _open_in_browser(self) -> None:
        """Hand the message to the real browser - for showing it to someone
        else, or printing it. Titan's own page view (Ctrl+W) is the usual way."""
        open_in_external_browser(self, self.message)

    def _save(self) -> None:
        subject = (self.message.get('subject') or 'message').strip() or 'message'
        safe = ''.join(char for char in subject if char.isalnum() or char in ' -_')[:60]
        wildcard = (_("Text file") + " (*.txt)|*.txt|" +
                    _("HTML file") + " (*.html)|*.html")
        dialog = wx.FileDialog(self, _("Save message"), defaultFile=safe or 'message',
                               wildcard=wildcard,
                               style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        apply_skin_tree(dialog)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        path = dialog.GetPath()
        dialog.Destroy()
        try:
            if path.lower().endswith('.html'):
                content = (self.message.get('body_html') or
                           mail_format.blocks_to_html(self.rendered.blocks))
            else:
                content = "{}: {}\n{}: {}\n{}: {}\n\n{}".format(
                    _("From"), self.message.get('from_addr') or '',
                    _("To"), self.message.get('to_addr') or '',
                    _("Subject"), subject, self.rendered.text())
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(content)
            speak_titannet(_("Saved as {name}").format(name=os.path.basename(path)))
        except Exception as exc:
            print(f"[Mail] save failed: {exc}")
            speak_notification(_("Could not save the message"), 'error')

    def _reply(self) -> None:
        open_compose(self, self.titan_client, self.message, forward=False)

    def _forward(self) -> None:
        open_compose(self, self.titan_client, self.message, forward=True)

    def _delete(self) -> None:
        mail_id = self.message.get('id')
        if not mail_id:
            return
        answer = show_message(self, _("Delete this message?"), _("Titan-Net Mail"),
                              wx.YES_NO | wx.ICON_QUESTION)
        if answer != wx.ID_YES:
            return

        def _do():
            result = self.titan_client.delete_mail(mail_id)
            wx.CallAfter(self._deleted, result)

        threading.Thread(target=_do, daemon=True).start()

    def _deleted(self, result: Dict[str, Any]) -> None:
        if not result.get('success'):
            play_sound('core/error.ogg')
            speak_notification(result.get('error') or _("Could not delete the message"),
                               'error')
            return
        speak_titannet(_("Message deleted"))
        parent = self.GetParent()
        self.Close()
        if isinstance(parent, MailFrame):
            parent.refresh()


# --------------------------------------------------------------------------- #
# Composer
# --------------------------------------------------------------------------- #
class ComposeMailFrame(wx.Frame):
    """Write a message in plain text, Markdown or HTML.

    A Titan window like any other - its own menu bar, status bar, skin and
    focus earcons - rather than a plain dialog. Nothing here is read out by
    Titan's own speech: the fields and the format list are ordinary controls,
    so the screen reader announces them itself, and speaking over that would
    only say everything twice. Titan speaks when it has something the controls
    cannot say: a validation error, "sending", the result.
    """

    def __init__(self, parent, titan_client, to_addr: str = '', subject: str = '',
                 body: str = '', fmt: str = '', on_sent=None):
        super().__init__(parent, title=_("Compose Mail"), size=(760, 640))
        self.titan_client = titan_client
        self.sent = False
        self.on_sent = on_sent
        self._formats = (mail_format.FORMAT_PLAIN, mail_format.FORMAT_MARKDOWN,
                         mail_format.FORMAT_HTML)
        self._initial_body = body

        self.InitUI(to_addr, subject, body,
                    fmt or get_setting('mail_compose_format',
                                       mail_format.FORMAT_PLAIN))
        self._build_menu()
        self.Centre()
        apply_skin_tree(self)
        self.Bind(wx.EVT_CHAR_HOOK, self.OnKeyPress)
        self.Bind(wx.EVT_CLOSE, self.OnCloseEvent)
        try:
            from src.ui.window_switcher import register_window
            register_window(_("Compose Mail"), window=self, category='messenger')
        except Exception:
            pass
        _play(MAIL_OPEN_SOUND)

    def InitUI(self, to_addr: str, subject: str, body: str, fmt: str) -> None:
        self.panel = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)

        self.header = wx.StaticText(self.panel, label=_("New message"))
        box.Add(self.header, flag=wx.ALL, border=8)

        box.Add(wx.StaticText(self.panel, label=_("To (username@domain or email):")),
                flag=wx.LEFT | wx.TOP, border=10)
        self.to_text = wx.TextCtrl(self.panel, value=to_addr)
        self.to_text.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        box.Add(self.to_text, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        box.Add(wx.StaticText(self.panel, label=_("Subject:")), flag=wx.LEFT | wx.TOP,
                border=10)
        self.subject_text = wx.TextCtrl(self.panel, value=subject)
        self.subject_text.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        box.Add(self.subject_text, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        box.Add(wx.StaticText(self.panel, label=_("Format:")), flag=wx.LEFT | wx.TOP,
                border=10)
        self.format_choice = wx.Choice(
            self.panel,
            choices=[mail_format.format_label(name) for name in self._formats])
        self.format_choice.SetSelection(
            self._formats.index(fmt) if fmt in self._formats else 0)
        self.format_choice.Bind(wx.EVT_CHOICE, self.OnFormat)
        self.format_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        box.Add(self.format_choice, flag=wx.LEFT | wx.RIGHT, border=10)

        self.hint = wx.StaticText(self.panel, label=self._hint())
        box.Add(self.hint, flag=wx.LEFT | wx.RIGHT | wx.TOP, border=10)

        box.Add(wx.StaticText(self.panel, label=_("Message:")), flag=wx.LEFT | wx.TOP,
                border=10)
        self.body_text = wx.TextCtrl(self.panel, value=body, style=wx.TE_MULTILINE)
        self.body_text.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        box.Add(self.body_text, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        for label, handler in ((_("Send"), self.OnSend),
                               (_("Preview"), self.OnPreview),
                               (_("Close"), self.Close)):
            button = wx.Button(self.panel, label=label)
            button.Bind(wx.EVT_BUTTON, lambda e, h=handler: h())
            button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
            buttons.Add(button, flag=wx.RIGHT, border=10)
            if label == _("Send"):
                self.send_button = button
        box.Add(buttons, flag=wx.ALL, border=10)

        self.panel.SetSizer(box)
        self.CreateStatusBar()
        self.SetStatusText(self._hint())

        if to_addr and not body:
            self.subject_text.SetFocus()
        elif body:
            self.body_text.SetInsertionPoint(0)
            self.body_text.SetFocus()
        else:
            self.to_text.SetFocus()

    def _build_menu(self) -> None:
        bar = wx.MenuBar()

        message = wx.Menu()
        self._menu_bind(message, _("Send\tCtrl+Enter"), self.OnSend)
        self._menu_bind(message, _("Preview\tF2"), self.OnPreview)
        message.AppendSeparator()
        self._menu_bind(message, _("Close\tEscape"), self.Close)
        bar.Append(message, _("&Message"))

        self.SetMenuBar(bar)

    def _menu_bind(self, menu: wx.Menu, label: str, handler) -> None:
        item = menu.Append(wx.ID_ANY, label)
        self.Bind(wx.EVT_MENU, lambda e: handler(), item)

    # -------------------------------------------------------------- behaviour
    def _format(self) -> str:
        index = self.format_choice.GetSelection()
        return self._formats[index] if 0 <= index < len(self._formats) \
            else mail_format.FORMAT_PLAIN

    def _hint(self) -> str:
        return {
            mail_format.FORMAT_PLAIN: _(
                "Plain text: sent exactly as typed."),
            mail_format.FORMAT_MARKDOWN: _(
                "Markdown: # heading, - list, > quote, **bold**, [text](address). "
                "Sent as written, with a formatted version alongside it."),
            mail_format.FORMAT_HTML: _(
                "HTML: write the markup yourself. A readable text version is "
                "sent alongside it."),
        }.get(self._format(), '')

    def OnFormat(self, event) -> None:
        # The choice announces itself; Titan only updates what it says next to
        # it and remembers the pick for the next message.
        self.hint.SetLabel(self._hint())
        self.SetStatusText(self._hint())
        set_setting('mail_compose_format', self._format())
        event.Skip()

    def OnFocus(self, event) -> None:
        play_sound('core/FOCUS.ogg', pan=0.5)
        event.Skip()

    def OnKeyPress(self, event) -> None:
        keycode = event.GetKeyCode()
        if _escape_pressed(event):
            self.Close()
            return
        if keycode == wx.WXK_F2:
            self.OnPreview()
            return
        if keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and event.ControlDown():
            self.OnSend()
            return
        event.Skip()

    def OnCloseEvent(self, event) -> None:
        if not self.sent and self.body_text.GetValue().strip() and \
                self.body_text.GetValue() != self._initial_body:
            answer = show_message(self, _("Discard this message?"),
                                  _("Compose Mail"), wx.YES_NO | wx.ICON_QUESTION)
            if answer != wx.ID_YES:
                if event.CanVeto():
                    event.Veto()
                return
        try:
            from src.ui.window_switcher import unregister_window
            unregister_window(_("Compose Mail"))
        except Exception:
            pass
        _play(MAIL_CLOSE_SOUND)
        event.Skip()

    def OnPreview(self) -> None:
        """Show the message as the recipient's Titan will read it."""
        body = self.body_text.GetValue()
        if not body.strip():
            speak_titannet(_("There is nothing to preview yet"))
            return
        play_sound('core/SELECT.ogg')
        outgoing = mail_format.build_outgoing(body, self._format())
        preview = {
            'from_addr': _("(preview)"),
            'to_addr': self.to_text.GetValue().strip(),
            'subject': self.subject_text.GetValue().strip(),
            'body': outgoing['body'],
            'body_html': outgoing['body_html'],
            'content_type': outgoing['content_type'],
            'received_at': time.strftime('%Y-%m-%dT%H:%M'),
        }
        frame = open_message(self, self.titan_client, preview, TAB_SENT)
        frame.SetTitle(_("Preview: {subject}").format(
            subject=preview['subject'] or _("(no subject)")))

    def OnSend(self) -> None:
        play_sound('core/SELECT.ogg')
        to_addr = self.to_text.GetValue().strip()
        subject = self.subject_text.GetValue().strip()
        body = self.body_text.GetValue()
        if not to_addr:
            speak_titannet(_("Please enter a recipient"))
            play_sound('core/error.ogg')
            self.to_text.SetFocus()
            return
        self.send_button.Enable(False)
        speak_titannet(_("Sending..."))
        outgoing = mail_format.build_outgoing(body, self._format())

        def _do():
            result = self.titan_client.send_mail(
                to_addr, subject, outgoing['body'],
                body_html=outgoing['body_html'],
                content_type=outgoing['content_type'])
            wx.CallAfter(self._on_sent, result)

        threading.Thread(target=_do, daemon=True).start()

    def _on_sent(self, result: Dict[str, Any]) -> None:
        if result.get('success'):
            play_sound('core/SELECT.ogg')
            speak_titannet(_("Message sent"))
            self.sent = True
            if self.on_sent:
                try:
                    self.on_sent()
                except Exception as exc:
                    print(f"[Mail] refresh after send failed: {exc}")
            self.Close()
            return
        self.send_button.Enable(True)
        play_sound('core/error.ogg')
        error = result.get('error') or _("Send failed")
        speak_notification(error, 'error')
        show_message(self, error, _("Compose Mail"), wx.OK | wx.ICON_ERROR)


def open_composer(parent, titan_client, to_addr: str = '', subject: str = '',
                  body: str = '', fmt: str = '', on_sent=None) -> ComposeMailFrame:
    """Open an empty (or prefilled) composer window."""
    frame = ComposeMailFrame(parent, titan_client, to_addr, subject, body, fmt,
                             on_sent=on_sent)
    frame.Show()
    return frame


def open_compose(parent, titan_client, message: Dict[str, Any],
                 forward: bool = False, on_sent=None) -> None:
    """Open the composer prefilled as a reply to - or a forward of - ``message``."""
    subject = (message.get('subject') or '').strip()
    prefix = 'Fwd: ' if forward else 'Re: '
    lowered = subject.lower()
    if forward:
        if not lowered.startswith(('fwd:', 'fw:')):
            subject = prefix + subject
    elif not lowered.startswith(('re:', 'odp:')):
        subject = prefix + subject

    author = (message.get('from_addr') or '').strip()
    quoted = mail_format.quote_body(message.get('body') or '',
                                    message.get('content_type') or '',
                                    message.get('body_html') or '',
                                    author=author)
    to_addr = '' if forward else author
    # A quoted body is Markdown-shaped ("> ..."), and Markdown is the format
    # that keeps it looking like a quote for the recipient too.
    open_composer(parent, titan_client, to_addr, subject, quoted,
                  fmt=mail_format.FORMAT_MARKDOWN, on_sent=on_sent)


def show_mail_client(parent, titan_client) -> Optional[MailFrame]:
    """Open the mailbox. Returns the frame, or None if it could not open."""
    try:
        frame = MailFrame(parent, titan_client)
        frame.Show()
        frame.listbox.SetFocus()
        return frame
    except Exception as exc:
        print(f"[Mail] could not open the mail client: {exc}")
        speak_notification(_("Could not open Mail"), 'error')
        return None
