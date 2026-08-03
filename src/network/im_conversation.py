# -*- coding: utf-8 -*-
"""The conversation window shared by the Titan IM web clients.

One rendered conversation: a list of messages with the same top tab bar as
everything else in Titan (Messages / Media / Files / Links / Participants), a
message field below it, and live updates pushed from the backend.

It is service-agnostic on purpose - it only speaks the ``im_web.base``
contract - so WhatsApp and Messenger behave identically here even though their
client windows are separate. Anything a service cannot do (reactions, editing,
deleting) is hidden through ``backend.has(...)`` rather than failing on use.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import wx

from src.network.im_web.base import (
    CAP_DELETE, CAP_EDIT, CAP_PARTICIPANTS, CAP_REACTIONS,
    EV_MEDIA_READY, EV_MESSAGE_NEW, EV_MESSAGE_UPDATED, EV_TYPING,
    Chat, Message,
)
from src.network.im_ui_common import (
    TabbedListFrame, _, apply_skin_tree, format_time, show_message, sounds,
    speak_notification, speak_titannet,
)
from src.titan_core.sound import play_sound

TAB_MESSAGES = 'messages'
TAB_MEDIA = 'media'
TAB_FILES = 'files'
TAB_LINKS = 'links'
TAB_PARTICIPANTS = 'participants'

MEDIA_KINDS = ('image', 'video', 'audio', 'voice', 'sticker')

# Reactions offered without asking the user to type an emoji.
QUICK_REACTIONS = (
    ('\U0001F44D', lambda: _("Thumbs up")),
    ('❤', lambda: _("Heart")),
    ('\U0001F602', lambda: _("Laughing")),
    ('\U0001F62E', lambda: _("Surprised")),
    ('\U0001F622', lambda: _("Sad")),
    ('\U0001F64F', lambda: _("Thanks")),
)


class ConversationFrame(TabbedListFrame):
    """One conversation, driven entirely by backend events."""

    VIEW_ID = 'titan_im_conversation'
    # Class level: the base class builds the list (and this label) inside
    # __init__, so setting it afterwards would come too late to be shown.
    LIST_LABEL = _("Messages:")

    def __init__(self, parent, backend, chat: Chat):
        self.backend = backend
        self.chat = chat
        self.messages: List[Message] = []
        self._typing_timer: Optional[wx.Timer] = None
        self._typing_sent = False
        self._oldest_id = ''
        self._has_more = True

        super().__init__(parent, title=_("{name} - {service}").format(
            name=chat.name, service=backend.SERVICE_LABEL), size=(900, 700))

        self.backend.add_listener(self._on_backend_event)
        self._build_menu()

        if sounds:
            try:
                sounds.window_open()
            except Exception:
                pass

        self.backend.mark_read(chat.id)
        self.refresh()

    # ------------------------------------------------------------------- setup
    def build_tabs(self) -> Sequence[Tuple[str, str]]:
        tabs = [
            (TAB_MESSAGES, _("Messages")),
            (TAB_MEDIA, _("Media")),
            (TAB_FILES, _("Files")),
            (TAB_LINKS, _("Links")),
        ]
        if self.chat.is_group and self.backend.has(CAP_PARTICIPANTS):
            tabs.append((TAB_PARTICIPANTS, _("Participants")))
        return tabs

    def build_footer(self, sizer: wx.BoxSizer) -> None:
        sizer.Add(wx.StaticText(self.panel, label=_("Your message:")),
                  flag=wx.LEFT | wx.RIGHT, border=8)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.input = wx.TextCtrl(self.panel, style=wx.TE_PROCESS_ENTER)
        self.input.Bind(wx.EVT_TEXT, self._on_input_changed)
        self.input.Bind(wx.EVT_TEXT_ENTER, lambda e: self._send())
        row.Add(self.input, proportion=1, flag=wx.EXPAND | wx.RIGHT, border=6)

        self.send_button = wx.Button(self.panel, label=_("Send"))
        self.send_button.Bind(wx.EVT_BUTTON, lambda e: self._send())
        row.Add(self.send_button)
        sizer.Add(row, flag=wx.EXPAND | wx.ALL, border=8)

    def _build_menu(self) -> None:
        bar = wx.MenuBar()

        conversation = wx.Menu()
        conversation.Append(wx.ID_ANY, _("Refresh\tF5"))
        self._menu_bind(conversation, _("Load earlier messages\tCtrl+Up"),
                        self._load_earlier)
        self._menu_bind(conversation, _("Send attachment...\tCtrl+O"),
                        self._send_attachment)
        self._menu_bind(conversation, _("Mark as read"),
                        lambda: self.backend.mark_read(self.chat.id))
        conversation.AppendSeparator()
        self._menu_bind(conversation, _("Voice call\tCtrl+T"),
                        lambda: self._start_call(False))
        self._menu_bind(conversation, _("Video call\tCtrl+Shift+T"),
                        lambda: self._start_call(True))
        conversation.AppendSeparator()
        self._menu_bind(conversation, _("Close\tEscape"), self.Close)
        bar.Append(conversation, _("&Conversation"))

        message_menu = wx.Menu()
        self._menu_bind(message_menu, _("Read whole message\tCtrl+R"),
                        self._speak_selected)
        self._menu_bind(message_menu, _("Copy text\tCtrl+C"), self._copy_selected)
        self._menu_bind(message_menu, _("Reply\tCtrl+Enter"), self._reply_selected)
        if self.backend.has(CAP_REACTIONS):
            self._menu_bind(message_menu, _("React..."), self._react_selected)
        if self.backend.has(CAP_EDIT):
            self._menu_bind(message_menu, _("Edit..."), self._edit_selected)
        if self.backend.has(CAP_DELETE):
            self._menu_bind(message_menu, _("Delete\tDelete"), self._delete_selected)
        self._menu_bind(message_menu, _("Download attachment"), self._download_selected)
        bar.Append(message_menu, _("&Message"))

        self.SetMenuBar(bar)

    def _menu_bind(self, menu: wx.Menu, label: str, handler) -> None:
        item = menu.Append(wx.ID_ANY, label)
        self.Bind(wx.EVT_MENU, lambda e: handler(), item)

    # -------------------------------------------------------------------- rows
    def load_items(self, tab_id: str, background: bool = False) -> None:
        if tab_id == TAB_PARTICIPANTS:
            self.backend.list_participants(
                self.chat.id,
                lambda result: self._apply_participants(result, tab_id,
                                                        background))
            return

        if tab_id == TAB_MESSAGES and not self.messages:
            if not background:
                # Opening a conversation the page has not rendered takes a
                # navigation and a couple of seconds - say so instead of
                # leaving the user in front of an empty list.
                speak_titannet(_("Loading the conversation..."))
            self.backend.load_history(
                self.chat.id, limit=60,
                callback=lambda result: self._apply_history(result, tab_id))
            return

        self.apply_items(self._filtered(tab_id), tab_id, background=background)

    def _filtered(self, tab_id: str) -> List[Any]:
        if tab_id == TAB_MEDIA:
            return [m for m in self.messages if m.kind in MEDIA_KINDS]
        if tab_id == TAB_FILES:
            return [m for m in self.messages if m.kind == 'document']
        if tab_id == TAB_LINKS:
            return [m for m in self.messages
                    if 'http://' in (m.text or '') or 'https://' in (m.text or '')]
        return list(self.messages)

    def _apply_history(self, result: Dict, tab_id: str) -> None:
        if not result.get('success'):
            speak_notification(result.get('error') or _("Could not load the conversation"),
                               'error')
            self.apply_items([], tab_id)
            return
        self.messages = list(result.get('messages') or [])
        self._has_more = bool(result.get('has_more'))
        if self.messages:
            self._oldest_id = self.messages[0].id
        self.apply_items(self._filtered(tab_id), tab_id)
        # Land on the newest message, not on the top of the history.
        if self.current_tab == TAB_MESSAGES and self.items:
            self.select_item_index(len(self.items) - 1)

    def _apply_participants(self, result: Dict, tab_id: str,
                            background: bool = False) -> None:
        if not result.get('success'):
            if not background:
                speak_notification(result.get('error') or
                                   _("Could not load participants"), 'error')
                self.apply_items([], tab_id)
            return
        self.apply_items(list(result.get('contacts') or []), tab_id,
                         background=background)

    def format_row(self, item: Any) -> str:
        if not isinstance(item, Message):
            # Participants tab.
            name = getattr(item, 'name', str(item))
            if getattr(item, 'extra', {}).get('is_admin'):
                return _("{name} (administrator)").format(name=name)
            return name

        who = _("You") if item.outgoing else (item.author or self.chat.name)
        stamp = format_time(item.timestamp)
        body = item.text or ''

        if item.deleted:
            body = _("(message deleted)")
        elif item.kind in MEDIA_KINDS or item.kind == 'document':
            label = {
                'image': _("photo"), 'video': _("video"), 'audio': _("audio"),
                'voice': _("voice message"), 'sticker': _("sticker"),
                'document': _("file"),
            }.get(item.kind, _("attachment"))
            name = (item.media or {}).get('name') or ''
            body = f"[{label}{': ' + name if name else ''}]{' ' + body if body else ''}"
        elif item.kind == 'call':
            body = _("[call]") + (f" {body}" if body else '')
        elif item.kind == 'system':
            return f"{stamp} {body}".strip()

        parts = [p for p in (stamp, f"{who}:", body) if p]
        text = ' '.join(parts)

        extras = []
        if item.edited:
            extras.append(_("edited"))
        if item.quoted:
            quoted_text = (item.quoted.get('text') or '')[:40]
            extras.append(_("replying to: {text}").format(text=quoted_text))
        for reaction in item.reactions or []:
            emoji = reaction.get('emoji') or ''
            if emoji:
                extras.append(_("reaction {emoji}").format(emoji=emoji))
        if item.outgoing and item.status:
            extras.append({
                'pending': _("sending"), 'sent': _("sent"),
                'delivered': _("delivered"), 'read': _("read"),
                'failed': _("not sent"),
            }.get(item.status, item.status))

        if extras:
            text = f"{text}, {', '.join(extras)}"
        return text

    def row_sound(self, item: Any, index: int) -> None:
        if isinstance(item, Message) and item.kind in MEDIA_KINDS:
            try:
                play_sound('ui/focus_expanded.ogg')
            except Exception:
                pass

    def status_text(self) -> str:
        if self.current_tab == TAB_MESSAGES:
            return _("{name}: {n} messages").format(name=self.chat.name,
                                                    n=len(self.items))
        return _("{tab}: {n} entries").format(tab=self.tab_label(self.current_tab),
                                              n=len(self.items))

    # ------------------------------------------------------------- activation
    def activate(self, item: Any) -> None:
        if not isinstance(item, Message):
            return
        if item.kind in MEDIA_KINDS or item.kind == 'document':
            self._download_selected(play=True)
            return
        self._speak_selected()

    def context_menu_items(self, item: Any):
        if not isinstance(item, Message):
            return ()
        entries = [
            (_("Read whole message"), self._speak_selected),
            (_("Copy text"), self._copy_selected),
            (_("Reply"), self._reply_selected),
        ]
        if self.backend.has(CAP_REACTIONS):
            entries.append((_("React..."), self._react_selected))
        if item.outgoing and self.backend.has(CAP_EDIT):
            entries.append((_("Edit..."), self._edit_selected))
        if self.backend.has(CAP_DELETE):
            entries.append((_("Delete"), self._delete_selected))
        if item.kind in MEDIA_KINDS or item.kind == 'document':
            entries.append((_("Download attachment"), self._download_selected))
        return entries

    def extra_key(self, keycode: int, modifiers: int, item: Optional[Any]) -> bool:
        # Ctrl+Up in the list pulls an older page of history.
        if keycode == wx.WXK_UP and modifiers == wx.MOD_CONTROL:
            self._load_earlier()
            return True
        if keycode == wx.WXK_DELETE and item is not None and \
                self.backend.has(CAP_DELETE) and self.FindFocus() is self.listbox:
            self._delete_selected()
            return True
        if keycode == wx.WXK_RETURN and modifiers == wx.MOD_CONTROL:
            self._reply_selected()
            return True
        # Typing anywhere but the input jumps to the input with that character.
        return False

    def on_escape(self) -> bool:
        return True

    def on_closed(self) -> None:
        self.backend.remove_listener(self._on_backend_event)
        if self._typing_timer is not None:
            self._typing_timer.Stop()
            self._typing_timer = None
        if self._typing_sent:
            self.backend.set_typing(self.chat.id, False)

    # --------------------------------------------------------------- sending
    def _send(self) -> None:
        text = self.input.GetValue().strip()
        if not text:
            return
        self.input.SetValue('')
        self._stop_typing()

        def _done(result: Dict) -> None:
            if result.get('success'):
                if sounds:
                    sounds.message_sent()
                return
            speak_notification(
                _("Message not sent: {error}").format(error=result.get('error') or ''),
                'error')
            # Put the text back so nothing is lost.
            if not self.input.GetValue():
                self.input.SetValue(text)

        self.backend.send_text(self.chat.id, text, callback=_done)

    def _reply_selected(self) -> None:
        item = self.selected_item()
        if not isinstance(item, Message):
            self.input.SetFocus()
            return
        dialog = wx.TextEntryDialog(
            self, _("Reply to: {text}").format(text=(item.text or '')[:60]),
            _("Reply"))
        apply_skin_tree(dialog)
        if dialog.ShowModal() == wx.ID_OK:
            text = dialog.GetValue().strip()
            if text:
                self.backend.reply_to(
                    self.chat.id, item.id, text,
                    callback=lambda result: self._report(result, _("Reply sent")))
        dialog.Destroy()

    def _send_attachment(self) -> None:
        dialog = wx.FileDialog(self, _("Choose a file to send"),
                               style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        apply_skin_tree(dialog)
        if dialog.ShowModal() == wx.ID_OK:
            path = dialog.GetPath()
            speak_titannet(_("Sending {name}").format(name=os.path.basename(path)))
            self.backend.send_attachment(
                self.chat.id, path,
                callback=lambda result: self._report(result, _("Attachment sent")))
        dialog.Destroy()

    def _report(self, result: Dict, success_text: str) -> None:
        if result.get('success'):
            if sounds:
                sounds.message_sent()
            speak_titannet(success_text)
        else:
            speak_notification(result.get('error') or _("Operation failed"), 'error')

    # ------------------------------------------------------------ message ops
    def _speak_selected(self) -> None:
        item = self.selected_item()
        if not isinstance(item, Message):
            return
        who = _("You") if item.outgoing else (item.author or self.chat.name)
        speak_titannet(f"{who}: {item.text or self.format_row(item)}")

    def _copy_selected(self) -> None:
        item = self.selected_item()
        if not isinstance(item, Message):
            return
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(item.text or ''))
            wx.TheClipboard.Close()
            speak_titannet(_("Copied"))

    def _react_selected(self) -> None:
        item = self.selected_item()
        if not isinstance(item, Message):
            return
        labels = [label() for _emoji, label in QUICK_REACTIONS]
        dialog = wx.SingleChoiceDialog(self, _("Choose a reaction"),
                                       _("React"), labels)
        apply_skin_tree(dialog)
        if dialog.ShowModal() == wx.ID_OK:
            emoji = QUICK_REACTIONS[dialog.GetSelection()][0]
            self.backend.react(
                self.chat.id, item.id, emoji,
                callback=lambda result: self._report(result, _("Reaction sent")))
        dialog.Destroy()

    def _edit_selected(self) -> None:
        item = self.selected_item()
        if not isinstance(item, Message) or not item.outgoing:
            speak_notification(_("Only your own messages can be edited"), 'warning')
            return
        dialog = wx.TextEntryDialog(self, _("New message text"), _("Edit message"),
                                    item.text or '')
        apply_skin_tree(dialog)
        if dialog.ShowModal() == wx.ID_OK:
            self.backend.edit_message(
                self.chat.id, item.id, dialog.GetValue(),
                callback=lambda result: self._report(result, _("Message edited")))
        dialog.Destroy()

    def _delete_selected(self) -> None:
        item = self.selected_item()
        if not isinstance(item, Message):
            return
        everyone = False
        if item.outgoing:
            answer = show_message(
                self, _("Delete this message for everyone?\n"
                        "Choosing No deletes it only for you."),
                _("Delete message"),
                wx.YES_NO | wx.CANCEL | wx.ICON_QUESTION)
            if answer == wx.ID_CANCEL:
                return
            everyone = (answer == wx.ID_YES)
        self.backend.delete_message(
            self.chat.id, item.id, everyone=everyone,
            callback=lambda result: self._report(result, _("Message deleted")))

    def _download_selected(self, play: bool = False) -> None:
        item = self.selected_item()
        if not isinstance(item, Message):
            return
        if not (item.kind in MEDIA_KINDS or item.kind == 'document'):
            speak_titannet(item.text or self.format_row(item))
            return

        speak_titannet(_("Downloading attachment"))

        def _done(result: Dict) -> None:
            if not result.get('success'):
                if sounds:
                    sounds.file_error()
                speak_notification(result.get('error') or _("Download failed"), 'error')
                return
            if sounds:
                sounds.file_success()
            path = result.get('path') or ''
            if play and item.kind in ('voice', 'audio'):
                self._play_audio(path)
            elif play:
                self._open_file(path)
            else:
                speak_titannet(_("Saved as {path}").format(path=path))

        self.backend.download_media(self.chat.id, item.id, callback=_done)

    def _play_audio(self, path: str) -> None:
        """Play a voice note through Titan's own audio pipeline."""
        def _work():
            try:
                from src.titan_core.sound import play_sound_file
                play_sound_file(path)
            except Exception as exc:
                print(f"[Titan IM] voice playback failed: {exc}")
                wx.CallAfter(self._open_file, path)
        threading.Thread(target=_work, daemon=True).start()

    def _open_file(self, path: str) -> None:
        try:
            os.startfile(path)  # noqa: S606 - user-initiated, Windows only
        except Exception as exc:
            speak_notification(_("Cannot open the file: {error}").format(error=exc),
                               'error')

    def _load_earlier(self) -> None:
        if not self._has_more:
            speak_titannet(_("No earlier messages"))
            return
        speak_titannet(_("Loading earlier messages"))

        def _done(result: Dict) -> None:
            if not result.get('success'):
                speak_notification(result.get('error') or _("Could not load history"),
                                   'error')
                return
            older = [m for m in (result.get('messages') or [])
                     if m.id not in {x.id for x in self.messages}]
            self._has_more = bool(result.get('has_more')) and bool(older)
            if not older:
                speak_titannet(_("No earlier messages"))
                return
            self.messages = older + self.messages
            self._oldest_id = self.messages[0].id
            self.apply_items(self._filtered(self.current_tab), self.current_tab)
            self.select_item_index(len(older))
            speak_titannet(_("Loaded {n} earlier messages").format(n=len(older)))

        self.backend.load_history(self.chat.id, before_id=self._oldest_id,
                                  limit=50, callback=_done)

    def _start_call(self, video: bool) -> None:
        self.backend.start_call(
            self.chat.id, video=video,
            callback=lambda result: self._report(
                result, _("Calling {name}").format(name=self.chat.name)))

    # ---------------------------------------------------------------- typing
    def _on_input_changed(self, event) -> None:
        event.Skip()
        if not self.input.GetValue():
            self._stop_typing()
            return
        if not self._typing_sent:
            self._typing_sent = True
            self.backend.set_typing(self.chat.id, True)
        if self._typing_timer is None:
            self._typing_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, lambda e: self._stop_typing(), self._typing_timer)
        self._typing_timer.Start(3000, oneShot=True)

    def _stop_typing(self) -> None:
        if self._typing_timer is not None:
            self._typing_timer.Stop()
        if self._typing_sent:
            self._typing_sent = False
            self.backend.set_typing(self.chat.id, False)

    # ----------------------------------------------------------- live events
    def _on_backend_event(self, event_type: str, payload: Any) -> None:
        if not isinstance(payload, dict):
            return

        if event_type == EV_MESSAGE_NEW:
            message = payload.get('message')
            if isinstance(message, Message) and message.chat_id == self.chat.id:
                wx.CallAfter(self._append_message, message)

        elif event_type == EV_MESSAGE_UPDATED:
            message = payload.get('message')
            if isinstance(message, Message) and message.chat_id == self.chat.id:
                wx.CallAfter(self._replace_message, message)

        elif event_type == EV_TYPING:
            if payload.get('chat_id') == self.chat.id and payload.get('typing'):
                wx.CallAfter(self._announce_typing)

        elif event_type == EV_MEDIA_READY:
            if payload.get('chat_id') == self.chat.id:
                wx.CallAfter(speak_titannet, _("Attachment ready: {name}").format(
                    name=payload.get('name') or ''))

    def _append_message(self, message: Message) -> None:
        if self._closing:
            return
        if any(m.id == message.id for m in self.messages):
            return
        self.messages.append(message)

        if sounds and not message.outgoing:
            try:
                # The conversation is open, so this is the quieter in-chat cue,
                # not the "you have a new message somewhere" one.
                sounds.chat_message()
            except Exception:
                pass

        if self.current_tab != TAB_MESSAGES:
            return

        at_end = self.listbox.GetSelection() >= self.listbox.GetCount() - 1
        self.items.append(message)
        self.listbox.Append(self.format_row(message), message)
        if at_end:
            self.listbox.SetSelection(self.listbox.GetCount() - 1)
            self._last_focus_idx = self.listbox.GetCount() - 1
        self.SetStatusText(self.status_text())

        if not message.outgoing:
            who = message.author or self.chat.name
            speak_titannet(f"{who}: {message.text or self.format_row(message)}")
            self.backend.mark_read(self.chat.id)

    def _replace_message(self, message: Message) -> None:
        if self._closing:
            return
        for index, existing in enumerate(self.messages):
            if existing.id != message.id:
                continue
            self.messages[index] = message
            for row in range(1, self.listbox.GetCount()):
                data = self.listbox.GetClientData(row)
                if isinstance(data, Message) and data.id == message.id:
                    self.listbox.SetString(row, self.format_row(message))
                    self.listbox.SetClientData(row, message)
                    break
            return

    def _announce_typing(self) -> None:
        if sounds:
            try:
                sounds.typing()
            except Exception:
                pass


def open_conversation(parent, backend, chat: Chat) -> Optional[ConversationFrame]:
    """Open (or raise) the conversation window for ``chat``."""
    existing = _open_windows.get((backend.SERVICE, chat.id))
    if existing is not None and existing:
        try:
            existing.Raise()
            existing.SetFocus()
            return existing
        except Exception:
            _open_windows.pop((backend.SERVICE, chat.id), None)

    frame = ConversationFrame(parent, backend, chat)
    _open_windows[(backend.SERVICE, chat.id)] = frame

    def _forget(event):
        _open_windows.pop((backend.SERVICE, chat.id), None)
        event.Skip()

    frame.Bind(wx.EVT_CLOSE, _forget)
    frame.Show()
    frame.listbox.SetFocus()
    return frame


_open_windows: Dict[Tuple[str, str], ConversationFrame] = {}
