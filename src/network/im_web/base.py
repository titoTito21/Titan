# -*- coding: utf-8 -*-
"""The service-agnostic contract every Titan IM web backend implements.

A backend owns one ``WebBridge`` (the offscreen page) and turns it into a plain
Python model: chats, messages, contacts, presence, calls. It never draws UI and
never speaks - the accessible client does that. Everything a client needs is
here, so the WhatsApp and Messenger clients differ only in the tabs and menus
they choose to show, not in how they talk to the service.

Events (backend -> client, via ``add_listener``)
-----------------------------------------------
``ready`` ``auth_state`` ``chats`` ``chat_updated`` ``messages`` ``message_new``
``message_updated`` ``typing`` ``presence`` ``call`` ``media_ready`` ``error``

Commands (client -> backend)
----------------------------
Every command takes an optional ``callback(result)`` where ``result`` is a dict
with ``success`` plus payload keys, or ``success: False`` and ``error`` - the
same shape the Titan-Net client uses, so the GUI code reads the same everywhere.

Capabilities
------------
The agent reports what the live page actually supports. A client asks
``backend.has(CAP_CHANNELS)`` and hides the tab when the answer is no, which is
also how the whole thing degrades gracefully when a service reshuffles its
internals: the affected capability disappears instead of the client raising.

Buffers
-------
Incoming traffic is pushed into the Titan Buffer System from *here*, not from
the GUI, so review buffers keep filling while the client window is closed and
neither client has to duplicate the logic.
"""

from __future__ import annotations

import base64
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

import wx

from src.network.im_web import bridge as bridge_mod

# --------------------------------------------------------------------- events
EV_READY = 'ready'
EV_AUTH_STATE = 'auth_state'
EV_CHATS = 'chats'
EV_CHAT_UPDATED = 'chat_updated'
EV_MESSAGES = 'messages'
EV_MESSAGE_NEW = 'message_new'
EV_MESSAGE_UPDATED = 'message_updated'
EV_TYPING = 'typing'
EV_PRESENCE = 'presence'
EV_CALL = 'call'
EV_MEDIA_READY = 'media_ready'
EV_ERROR = 'error'
EV_LOG = 'log'

# --------------------------------------------------------------- capabilities
CAP_CHANNELS = 'channels'
CAP_STATUS_UPDATES = 'status_updates'
CAP_REACTIONS = 'reactions'
CAP_EDIT = 'edit'
CAP_VOICE_NOTES = 'voice_notes'
CAP_MESSAGE_REQUESTS = 'message_requests'
CAP_COMMUNITIES = 'communities'
CAP_VIDEO_CALL = 'video_call'
CAP_VOICE_CALL = 'voice_call'
CAP_ATTACHMENTS = 'attachments'
CAP_SEARCH = 'search'
CAP_PARTICIPANTS = 'participants'
CAP_ARCHIVE = 'archive'
CAP_DELETE = 'delete'
CAP_PRESENCE = 'presence'

# ------------------------------------------------------------------ auth states
AUTH_LOADING = 'loading'
AUTH_LOGGED_OUT = 'logged_out'
AUTH_QR = 'qr'
AUTH_PAIRING = 'pairing'
AUTH_CHALLENGE = 'challenge'     # checkpoint / 2FA / captcha - needs the real page
AUTH_LOGGED_IN = 'logged_in'

_UPLOAD_CHUNK = 192 * 1024       # base64 characters per RunScriptAsync call
_DOWNLOAD_CHUNK = 192 * 1024

# Opening a conversation the page has not rendered costs a navigation: the
# command is re-asked after the new document has had time to bring its agent up.
NAV_RETRY_MS = 2500
MAX_NAV_RETRIES = 4


def media_dir(service: str) -> str:
    """Where received attachments are written: inside the per-user Titan data dir."""
    from src.platform_utils import get_user_data_dir
    root = os.path.join(get_user_data_dir(), 'IM MEDIA', service)
    os.makedirs(root, exist_ok=True)
    return root


# ----------------------------------------------------------------- data model
@dataclass
class Chat:
    id: str
    name: str
    is_group: bool = False
    unread: int = 0
    last_message: str = ''
    last_message_at: float = 0.0
    last_author: str = ''
    muted: bool = False
    archived: bool = False
    pinned: bool = False
    online: bool = False
    kind: str = 'chat'           # chat | group | channel | status | request
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Chat':
        known = {
            'id': str(data.get('id') or ''),
            'name': (data.get('name') or '').strip() or str(data.get('id') or '?'),
            'is_group': bool(data.get('is_group')),
            'unread': int(data.get('unread') or 0),
            'last_message': data.get('last_message') or '',
            'last_message_at': float(data.get('last_message_at') or 0),
            'last_author': data.get('last_author') or '',
            'muted': bool(data.get('muted')),
            'archived': bool(data.get('archived')),
            'pinned': bool(data.get('pinned')),
            'online': bool(data.get('online')),
            'kind': data.get('kind') or ('group' if data.get('is_group') else 'chat'),
        }
        known['extra'] = {k: v for k, v in data.items() if k not in known}
        return cls(**known)


@dataclass
class Message:
    id: str
    chat_id: str
    text: str = ''
    author: str = ''
    author_id: str = ''
    timestamp: float = 0.0
    outgoing: bool = False
    kind: str = 'text'           # text|image|video|audio|voice|document|sticker|location|system|call
    status: str = ''             # pending|sent|delivered|read|failed
    edited: bool = False
    deleted: bool = False
    quoted: Optional[Dict[str, Any]] = None
    reactions: List[Dict[str, Any]] = field(default_factory=list)
    media: Optional[Dict[str, Any]] = None   # {name, mime, size, duration}
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_media(self) -> bool:
        return self.kind in ('image', 'video', 'audio', 'voice', 'document', 'sticker')

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        known = {
            'id': str(data.get('id') or ''),
            'chat_id': str(data.get('chat_id') or ''),
            'text': data.get('text') or '',
            'author': data.get('author') or '',
            'author_id': str(data.get('author_id') or ''),
            'timestamp': float(data.get('timestamp') or 0),
            'outgoing': bool(data.get('outgoing')),
            'kind': data.get('kind') or 'text',
            'status': data.get('status') or '',
            'edited': bool(data.get('edited')),
            'deleted': bool(data.get('deleted')),
            'quoted': data.get('quoted'),
            'reactions': list(data.get('reactions') or []),
            'media': data.get('media'),
        }
        known['extra'] = {k: v for k, v in data.items() if k not in known}
        return cls(**known)


@dataclass
class Contact:
    id: str
    name: str
    online: bool = False
    last_seen: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Contact':
        return cls(
            id=str(data.get('id') or ''),
            name=(data.get('name') or '').strip() or str(data.get('id') or '?'),
            online=bool(data.get('online')),
            last_seen=float(data.get('last_seen') or 0),
            extra={k: v for k, v in data.items()
                   if k not in ('id', 'name', 'online', 'last_seen')},
        )


@dataclass
class CallState:
    state: str = 'idle'          # idle|ringing_in|ringing_out|connected|ended
    peer: str = ''
    peer_id: str = ''
    video: bool = False
    started_at: float = 0.0

    @property
    def active(self) -> bool:
        return self.state in ('ringing_in', 'ringing_out', 'connected')


# --------------------------------------------------------------------- backend
class IMBackend:
    """Base class: owns the engine, the caches, the buffers and the commands."""

    SERVICE = ''                 # 'whatsapp' | 'messenger'
    SERVICE_LABEL = ''           # human readable, already translated by the subclass
    URL = ''
    BUFFER_CATEGORY = ''         # buffer system category id
    DEFAULT_CAPABILITIES: Set[str] = set()

    def __init__(self):
        self.bridge: Optional[bridge_mod.WebBridge] = None
        self.chats: Dict[str, Chat] = {}
        self.contacts: Dict[str, Contact] = {}
        self.call = CallState()
        self.auth: Dict[str, Any] = {'state': AUTH_LOADING}
        self.capabilities: Set[str] = set(self.DEFAULT_CAPABILITIES)
        self.last_error: str = ''

        self._listeners: List[Callable[[str, Any], None]] = []
        self._buffers_registered = False
        # Last good conversation list per scope, and histories per chat: the
        # page loses these on every reload, this process does not.
        self._chat_cache: Dict[str, List[Chat]] = {}
        self._history_cache: Dict[str, List[Message]] = {}

    # ------------------------------------------------------------- lifecycle
    def build_agent_js(self) -> str:
        """Return the service-specific agent script. Subclass responsibility."""
        raise NotImplementedError

    def start(self) -> None:
        """Bring the engine up. Safe to call again; reuses a running engine."""
        existing = bridge_mod.get_bridge(self.SERVICE)
        if existing is not None:
            self.bridge = existing
            self.bridge.add_listener(self._on_bridge_event)
            if self.bridge.ready:
                self.refresh_auth_state()
            return

        # The title is only ever read when the page is deliberately shown for a
        # login step, so it names what the user is looking at.
        self.bridge = bridge_mod.WebBridge(
            service=self.SERVICE, url=self.URL, agent_js=self.build_agent_js(),
            title=_page_title_label(self.SERVICE_LABEL or self.SERVICE))
        self.bridge.add_listener(self._on_bridge_event)
        bridge_mod.register_bridge(self.SERVICE, self.bridge)
        self.bridge.start()

    def stop(self, keep_engine: bool = True) -> None:
        """Detach this backend. With ``keep_engine`` the page keeps running.

        Keeping it is the normal case: closing the client window should not log
        the user out or drop incoming traffic that still feeds the buffers.
        """
        if self.bridge is not None:
            self.bridge.remove_listener(self._on_bridge_event)
            if not keep_engine:
                self.bridge.stop()
                bridge_mod.drop_bridge(self.SERVICE)
                self._remove_buffers()
        self.bridge = None

    @property
    def running(self) -> bool:
        return self.bridge is not None

    @property
    def ready(self) -> bool:
        return self.bridge is not None and self.bridge.ready

    @property
    def logged_in(self) -> bool:
        return self.auth.get('state') == AUTH_LOGGED_IN

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    # ----------------------------------------------------------------- events
    def add_listener(self, callback: Callable[[str, Any], None]) -> None:
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[str, Any], None]) -> None:
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _emit(self, event_type: str, payload: Any) -> None:
        """Fan an event out to listeners and to the buffer system."""
        self._buffer_push(event_type, payload)
        for callback in list(self._listeners):
            try:
                callback(event_type, payload)
            except Exception as exc:
                print(f"[{self.SERVICE}] listener error on '{event_type}': {exc}")

    def _on_bridge_event(self, event_type: str, payload: Any) -> None:
        """Translate a raw agent event into the model, then re-emit it."""
        try:
            if event_type == EV_READY:
                reported = set((payload or {}).get('capabilities') or [])
                self.capabilities = reported or set(self.DEFAULT_CAPABILITIES)
                self.refresh_auth_state()

            elif event_type == EV_AUTH_STATE:
                payload = self._apply_auth_state(payload or {})

            elif event_type == EV_CHATS:
                payload = self._apply_chats(payload or {})

            elif event_type == EV_CHAT_UPDATED:
                payload = self._apply_chat_updated(payload or {})

            elif event_type in (EV_MESSAGE_NEW, EV_MESSAGE_UPDATED):
                payload = self._apply_message(event_type, payload or {})

            elif event_type == EV_MESSAGES:
                raw = (payload or {}).get('messages') or []
                payload = dict(payload or {})
                payload['messages'] = [Message.from_dict(m) for m in raw]

            elif event_type == EV_PRESENCE:
                payload = self._apply_presence(payload or {})

            elif event_type == EV_CALL:
                payload = self._apply_call(payload or {})

            elif event_type == EV_ERROR:
                self.last_error = (payload or {}).get('message') or ''
                print(f"[{self.SERVICE}] agent error: {payload}")

            elif event_type == EV_LOG:
                print(f"[{self.SERVICE}] {(payload or {}).get('message')}")
                return

            elif event_type == 'bridge_loaded':
                return

            elif event_type == 'page_hidden':
                # Closing the visible page usually means "I have just logged in
                # there" - ask the agent immediately rather than waiting.
                self.refresh_auth_state()
                return
        except Exception as exc:
            print(f"[{self.SERVICE}] failed to translate '{event_type}': {exc}")
            return

        self._emit(event_type, payload)

    # --------------------------------------------------- event -> model updates
    def _apply_auth_state(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        was_logged_in = self.logged_in
        self.auth = dict(payload)
        if self.logged_in:
            if not was_logged_in:
                self._register_buffers()
                self.list_chats()
        elif was_logged_in:
            self._remove_buffers()
        return payload

    def _apply_chats(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        chats = [Chat.from_dict(c) for c in (payload.get('chats') or [])]
        if not chats and self.chats:
            # An empty snapshot from a page that had conversations a moment ago
            # is the list being re-rendered - it must not clear the model.
            payload = dict(payload)
            payload['chats'] = []
            payload['stale'] = True
            return payload
        if payload.get('partial'):
            for chat in chats:
                self.chats[chat.id] = chat
        else:
            self.chats = {chat.id: chat for chat in chats}
        out = dict(payload)
        out['chats'] = chats
        return out

    def _apply_chat_updated(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        chat = Chat.from_dict(payload.get('chat') or payload)
        if chat.id:
            self.chats[chat.id] = chat
        out = dict(payload)
        out['chat'] = chat
        return out

    def _apply_message(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        message = Message.from_dict(payload.get('message') or payload)
        chat = self.chats.get(message.chat_id)
        if chat is not None and event_type == EV_MESSAGE_NEW:
            chat.last_message = message.text or message.kind
            chat.last_message_at = message.timestamp or time.time()
            chat.last_author = message.author
            if not message.outgoing:
                chat.unread += 1
        out = dict(payload)
        out['message'] = message
        return out

    def _apply_presence(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        contact = Contact.from_dict(payload.get('contact') or payload)
        if contact.id:
            self.contacts[contact.id] = contact
        chat = self.chats.get(contact.id)
        if chat is not None:
            chat.online = contact.online
        out = dict(payload)
        out['contact'] = contact
        return out

    def _apply_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        state = payload.get('state') or 'idle'
        self.call = CallState(
            state=state,
            peer=payload.get('peer') or '',
            peer_id=str(payload.get('peer_id') or ''),
            video=bool(payload.get('video')),
            started_at=float(payload.get('started_at') or 0) or (
                time.time() if state == 'connected' else 0.0),
        )
        out = dict(payload)
        out['call'] = self.call
        return out

    # ---------------------------------------------------------------- buffers
    def _register_buffers(self) -> None:
        if self._buffers_registered or not self.BUFFER_CATEGORY:
            return
        try:
            from src.buffers import defaults as buffer_defaults
            register = getattr(buffer_defaults, f'register_{self.BUFFER_CATEGORY}', None)
            if register:
                register(with_channels=self.has(CAP_CHANNELS))
                self._buffers_registered = True
        except Exception as exc:
            print(f"[{self.SERVICE}] buffer registration failed: {exc}")

    def _remove_buffers(self) -> None:
        if not self._buffers_registered:
            return
        try:
            from src.buffers import defaults as buffer_defaults
            remove = getattr(buffer_defaults, f'remove_{self.BUFFER_CATEGORY}', None)
            if remove:
                remove()
        except Exception as exc:
            print(f"[{self.SERVICE}] buffer removal failed: {exc}")
        self._buffers_registered = False

    def _buffer_target(self, message: Message) -> str:
        chat = self.chats.get(message.chat_id)
        kind = chat.kind if chat is not None else 'chat'
        if kind in ('channel', 'status'):
            return 'channels'
        if kind == 'group' or (chat is not None and chat.is_group):
            return 'groups'
        return 'pm'

    def _buffer_push(self, event_type: str, payload: Any) -> None:
        """Mirror user-visible traffic into the Titan Buffer System."""
        if not self.BUFFER_CATEGORY or not isinstance(payload, dict):
            return
        try:
            from src.buffers import buffer_bus
        except Exception:
            return

        try:
            if event_type == EV_MESSAGE_NEW:
                message = payload.get('message')
                if not isinstance(message, Message) or message.deleted:
                    return
                chat = self.chats.get(message.chat_id)
                chat_name = chat.name if chat is not None else message.chat_id
                author = message.author or (
                    _me_label() if message.outgoing else chat_name)
                body = message.text or _media_label(message.kind)
                text = f"{chat_name}: {body}" if (chat and chat.is_group) else body
                buffer_bus.push(
                    self.BUFFER_CATEGORY, self._buffer_target(message), text,
                    author=author, kind='private' if not (chat and chat.is_group) else 'message',
                    raw={'service': self.SERVICE, 'chat_id': message.chat_id,
                         'msg_id': message.id},
                    timestamp=message.timestamp or None,
                    # What we sent ourselves belongs in the review buffer, but
                    # pinging the user about their own typing is just noise.
                    silent=bool(message.outgoing))

            elif event_type == EV_CALL:
                call = payload.get('call')
                if not isinstance(call, CallState) or call.state == 'idle':
                    return
                buffer_bus.push(
                    self.BUFFER_CATEGORY, 'calls',
                    _call_label(call), author=call.peer, kind='notification',
                    raw={'service': self.SERVICE, 'peer_id': call.peer_id})

            elif event_type == EV_MESSAGE_UPDATED:
                message = payload.get('message')
                if not isinstance(message, Message):
                    return
                note = payload.get('note') or ''
                if not note:
                    return
                buffer_bus.push(
                    self.BUFFER_CATEGORY, 'notifications', note,
                    author=message.author, kind='notification',
                    raw={'service': self.SERVICE, 'chat_id': message.chat_id,
                         'msg_id': message.id})

            elif event_type == EV_ERROR:
                message = payload.get('message')
                if message:
                    buffer_bus.push(self.BUFFER_CATEGORY, 'notifications',
                                    str(message), kind='notification',
                                    raw={'service': self.SERVICE})
        except Exception as exc:
            print(f"[{self.SERVICE}] buffer push failed: {exc}")

    # --------------------------------------------------------------- commands
    def _call(self, cmd: str, args: Optional[Dict[str, Any]] = None,
              callback: Optional[Callable[[Dict[str, Any]], None]] = None,
              parse: Optional[Callable[[Any], Dict[str, Any]]] = None,
              timeout: float = bridge_mod.DEFAULT_TIMEOUT) -> None:
        """Send one command, normalising the answer into a result dict."""
        if self.bridge is None:
            if callback:
                wx.CallAfter(callback, {'success': False,
                                        'error': _not_running_label()})
            return

        def _relay(ok: bool, data: Any) -> None:
            if not ok:
                if callback:
                    callback({'success': False, 'error': str(data)})
                else:
                    print(f"[{self.SERVICE}] '{cmd}' failed: {data}")
                return
            result: Dict[str, Any] = {'success': True}
            try:
                if parse is not None:
                    result.update(parse(data))
                elif isinstance(data, dict):
                    result.update(data)
                else:
                    result['result'] = data
            except Exception as exc:
                result = {'success': False, 'error': f"bad reply: {exc}"}
            if callback:
                callback(result)

        self.bridge.call(cmd, args or {}, _relay, timeout=timeout)

    # -- auth ---------------------------------------------------------------
    def refresh_auth_state(self, callback=None) -> None:
        self._call('auth_state', {}, callback)

    def login_start(self, method: str = 'default', callback=None, **kwargs) -> None:
        """Begin a login. ``method`` is service specific (pairing code, form)."""
        args = {'method': method}
        args.update(kwargs)
        self._call('login_start', args, callback, timeout=60.0)

    def logout(self, callback=None) -> None:
        self._call('logout', {}, callback, timeout=45.0)

    # -- chats & messages ----------------------------------------------------
    def list_chats(self, scope: str = 'all', callback=None) -> None:
        """Read the conversation list, falling back to the last good read.

        The page is not a reliable source: it re-renders, navigates and gets
        reloaded, and a read taken at the wrong moment comes back empty or
        times out. This process outlives all of that, so the last non-empty
        answer per scope is kept here and handed out (marked ``stale``) rather
        than reporting "no conversations" to a logged-in user.
        """
        def _parse(data):
            chats = [Chat.from_dict(c) for c in (data or {}).get('chats') or []]
            return {'chats': chats}

        def _relay(result: Dict[str, Any]) -> None:
            chats = result.get('chats') or []
            if chats:
                self._chat_cache[scope] = list(chats)
            else:
                cached = self._chat_cache.get(scope) or []
                if cached:
                    result = {'success': True, 'chats': list(cached), 'stale': True}
            if callback:
                callback(result)

        self._call('list_chats', {'scope': scope}, _relay, _parse, timeout=45.0)

    def open_chat(self, chat_id: str, callback=None) -> None:
        self._call('open_chat', {'chat_id': chat_id}, callback, timeout=30.0)

    def load_history(self, chat_id: str, before_id: str = '', limit: int = 50,
                     callback=None, _attempt: int = 0) -> None:
        """Read a conversation, waiting out a page navigation if one is needed.

        Opening a conversation the page has not rendered means a real
        navigation, which tears down the document the command was running in.
        The agent says ``navigating`` instead of dying in a timeout, and the
        question is simply asked again once the new page has its agent.
        """
        def _parse(data):
            data = data or {}
            messages = [Message.from_dict(m) for m in data.get('messages') or []]
            return {'messages': messages,
                    'has_more': bool(data.get('has_more')),
                    'navigating': bool(data.get('navigating'))}

        def _relay(result: Dict[str, Any]) -> None:
            if result.get('navigating') and _attempt < MAX_NAV_RETRIES:
                wx.CallLater(NAV_RETRY_MS, self.load_history, chat_id,
                             before_id, limit, callback, _attempt + 1)
                return

            messages = result.get('messages') or []
            if messages and not before_id:
                self._history_cache[chat_id] = list(messages)
            elif not messages and not before_id:
                cached = self._history_cache.get(chat_id) or []
                if cached:
                    # Same rule as the conversation list: a read taken while
                    # the thread is not rendered is not an empty conversation.
                    result = {'success': True, 'messages': list(cached),
                              'has_more': True, 'stale': True}
            if callback:
                callback(result)

        self._call('load_history',
                   {'chat_id': chat_id, 'before_id': before_id, 'limit': limit},
                   _relay, _parse, timeout=45.0)

    def send_text(self, chat_id: str, text: str, callback=None) -> None:
        self._call('send_text', {'chat_id': chat_id, 'text': text},
                   callback, timeout=45.0)

    def reply_to(self, chat_id: str, msg_id: str, text: str, callback=None) -> None:
        self._call('reply_to', {'chat_id': chat_id, 'msg_id': msg_id, 'text': text},
                   callback, timeout=45.0)

    def react(self, chat_id: str, msg_id: str, emoji: str, callback=None) -> None:
        self._call('react', {'chat_id': chat_id, 'msg_id': msg_id, 'emoji': emoji},
                   callback)

    def edit_message(self, chat_id: str, msg_id: str, text: str, callback=None) -> None:
        self._call('edit_message', {'chat_id': chat_id, 'msg_id': msg_id, 'text': text},
                   callback)

    def delete_message(self, chat_id: str, msg_id: str, everyone: bool = False,
                       callback=None) -> None:
        self._call('delete_message',
                   {'chat_id': chat_id, 'msg_id': msg_id, 'everyone': everyone},
                   callback)

    def mark_read(self, chat_id: str, callback=None) -> None:
        chat = self.chats.get(chat_id)
        if chat is not None:
            chat.unread = 0
        self._call('mark_read', {'chat_id': chat_id}, callback)

    def search(self, query: str, chat_id: str = '', callback=None) -> None:
        def _parse(data):
            return {
                'messages': [Message.from_dict(m)
                             for m in (data or {}).get('messages') or []],
                'chats': [Chat.from_dict(c) for c in (data or {}).get('chats') or []],
            }
        self._call('search', {'query': query, 'chat_id': chat_id},
                   callback, _parse, timeout=45.0)

    def list_participants(self, chat_id: str, callback=None) -> None:
        def _parse(data):
            return {'contacts': [Contact.from_dict(c)
                                 for c in (data or {}).get('contacts') or []]}
        self._call('list_participants', {'chat_id': chat_id}, callback, _parse)

    def list_contacts(self, callback=None) -> None:
        def _parse(data):
            contacts = [Contact.from_dict(c) for c in (data or {}).get('contacts') or []]
            for contact in contacts:
                self.contacts[contact.id] = contact
            return {'contacts': contacts}
        self._call('list_contacts', {}, callback, _parse, timeout=45.0)

    def set_presence(self, online: bool, callback=None) -> None:
        self._call('set_presence', {'online': online}, callback)

    def set_typing(self, chat_id: str, typing: bool, callback=None) -> None:
        self._call('set_typing', {'chat_id': chat_id, 'typing': typing}, callback)

    # -- calls ---------------------------------------------------------------
    def start_call(self, chat_id: str, video: bool = False, callback=None) -> None:
        self._call('start_call', {'chat_id': chat_id, 'video': video},
                   callback, timeout=30.0)

    def accept_call(self, callback=None) -> None:
        self._call('accept_call', {}, callback)

    def end_call(self, callback=None) -> None:
        self._call('end_call', {}, callback)

    # -- diagnostics ---------------------------------------------------------
    def self_test(self, callback=None) -> None:
        self._call('__self_test', {}, callback)

    def show_page(self) -> None:
        if self.bridge is not None:
            self.bridge.show_page()

    def hide_page(self) -> None:
        if self.bridge is not None:
            self.bridge.hide_page()

    @property
    def page_visible(self) -> bool:
        return self.bridge is not None and self.bridge.page_visible

    # -- attachments ---------------------------------------------------------
    def send_attachment(self, chat_id: str, path: str, caption: str = '',
                        callback=None) -> None:
        """Upload ``path`` into the page in chunks, then let the agent send it."""
        if self.bridge is None:
            if callback:
                wx.CallAfter(callback, {'success': False, 'error': _not_running_label()})
            return
        try:
            with open(path, 'rb') as handle:
                data = base64.b64encode(handle.read()).decode('ascii')
        except Exception as exc:
            if callback:
                wx.CallAfter(callback, {'success': False, 'error': str(exc)})
            return

        blob_id = uuid.uuid4().hex
        name = os.path.basename(path)
        mime = _guess_mime(path)
        chunks = [data[i:i + _UPLOAD_CHUNK] for i in range(0, len(data), _UPLOAD_CHUNK)] or ['']

        def _fail(error):
            self.bridge.call('__blob_drop', {'id': blob_id})
            if callback:
                callback({'success': False, 'error': str(error)})

        def _send_chunk(index: int):
            if index >= len(chunks):
                self.bridge.call('__blob_end', {'id': blob_id}, _finished, timeout=60.0)
                return
            self.bridge.call(
                '__blob_chunk', {'id': blob_id, 'data': chunks[index]},
                lambda ok, data_, i=index: (_send_chunk(i + 1) if ok else _fail(data_)),
                timeout=60.0)

        def _finished(ok, data_):
            if not ok:
                _fail(data_)
                return
            self._call('send_attachment',
                       {'chat_id': chat_id, 'blob_id': blob_id, 'caption': caption,
                        'name': name, 'mime': mime},
                       lambda result: (self.bridge.call('__blob_drop', {'id': blob_id}),
                                       callback(result) if callback else None),
                       timeout=180.0)

        self.bridge.call('__blob_begin', {'id': blob_id, 'name': name, 'mime': mime},
                         lambda ok, data_: (_send_chunk(0) if ok else _fail(data_)),
                         timeout=60.0)

    def download_media(self, chat_id: str, msg_id: str, callback=None) -> None:
        """Fetch a message's media through the page and write it to disk.

        ``callback({'success': True, 'path': ..., 'name': ...})``; the same
        information also goes out as a ``media_ready`` event so a client that
        was not the requester (or reopened meanwhile) still learns about it.
        """
        if self.bridge is None:
            if callback:
                wx.CallAfter(callback, {'success': False, 'error': _not_running_label()})
            return

        def _on_descriptor(ok, data):
            if not ok:
                if callback:
                    callback({'success': False, 'error': str(data)})
                return
            descriptor = data or {}
            blob_id = descriptor.get('blob_id')
            total = int(descriptor.get('length') or 0)
            name = descriptor.get('name') or f"{msg_id}.bin"

            if not blob_id and descriptor.get('url'):
                # Messenger's CDN often refuses a cross-origin read inside the
                # page, so the agent hands over the (already signed) URL and we
                # fetch it here instead of giving up.
                self._download_url(descriptor['url'], name, chat_id, msg_id, callback)
                return

            if not blob_id or total <= 0:
                if callback:
                    callback({'success': False, 'error': _no_media_label()})
                return

            parts: List[str] = []

            def _read(offset: int):
                self.bridge.call(
                    '__blob_read',
                    {'id': blob_id, 'offset': offset, 'length': _DOWNLOAD_CHUNK},
                    lambda ok_, payload: _on_chunk(ok_, payload, offset),
                    timeout=60.0)

            def _on_chunk(ok_, payload, offset):
                if not ok_:
                    self.bridge.call('__blob_drop', {'id': blob_id})
                    if callback:
                        callback({'success': False, 'error': str(payload)})
                    return
                chunk = (payload or {}).get('data') or ''
                parts.append(chunk)
                next_offset = offset + len(chunk)
                if chunk and next_offset < total:
                    _read(next_offset)
                    return
                self.bridge.call('__blob_drop', {'id': blob_id})
                _write(''.join(parts))

            def _write(encoded: str):
                try:
                    raw = base64.b64decode(encoded)
                    target = os.path.join(media_dir(self.SERVICE),
                                          _safe_name(name, msg_id))
                    with open(target, 'wb') as handle:
                        handle.write(raw)
                except Exception as exc:
                    if callback:
                        callback({'success': False, 'error': str(exc)})
                    return
                result = {'success': True, 'path': target, 'name': name,
                          'chat_id': chat_id, 'msg_id': msg_id}
                self._emit(EV_MEDIA_READY, dict(result))
                if callback:
                    callback(result)

            _read(0)

        self.bridge.call('download_media', {'chat_id': chat_id, 'msg_id': msg_id},
                         _on_descriptor, timeout=180.0)

    def _download_url(self, url: str, name: str, chat_id: str, msg_id: str,
                      callback=None) -> None:
        """Fetch a signed media URL outside the page, on a worker thread."""
        import threading

        def _work():
            try:
                import requests
                response = requests.get(url, timeout=60)
                response.raise_for_status()
                target = os.path.join(media_dir(self.SERVICE), _safe_name(name, msg_id))
                with open(target, 'wb') as handle:
                    handle.write(response.content)
            except Exception as exc:
                if callback:
                    wx.CallAfter(callback, {'success': False, 'error': str(exc)})
                return
            result = {'success': True, 'path': target, 'name': name,
                      'chat_id': chat_id, 'msg_id': msg_id}
            wx.CallAfter(self._emit, EV_MEDIA_READY, dict(result))
            if callback:
                wx.CallAfter(callback, result)

        threading.Thread(target=_work, daemon=True).start()


# --------------------------------------------------------------------------- #
#  Small translated labels. Imported lazily so this module stays UI-free and
#  cannot pull the translation machinery in at import time.
# --------------------------------------------------------------------------- #
def _t():
    try:
        from src.titan_core.translation import set_language
        from src.settings.settings import get_setting
        return set_language(get_setting('language', 'pl'))
    except Exception:
        return lambda text: text


# These bind ``_`` first: the string extractor only recognises the _("...")
# form, so ``_t()("...")`` would silently stay untranslated.
def _not_running_label() -> str:
    _ = _t()
    return _("The service engine is not running")


def _no_media_label() -> str:
    _ = _t()
    return _("This message has no downloadable media")


def _me_label() -> str:
    _ = _t()
    return _("Me")


def _page_title_label(service_label: str) -> str:
    _ = _t()
    return _("{service} web page - Titan IM").format(service=service_label)


def _media_label(kind: str) -> str:
    _ = _t()
    return {
        'image': _("Photo"),
        'video': _("Video"),
        'audio': _("Audio"),
        'voice': _("Voice message"),
        'document': _("Document"),
        'sticker': _("Sticker"),
        'location': _("Location"),
        'call': _("Call"),
        'system': _("System message"),
    }.get(kind, _("Message"))


def _call_label(call: CallState) -> str:
    _ = _t()
    kind = _("Video call") if call.video else _("Voice call")
    state = {
        'ringing_in': _("incoming"),
        'ringing_out': _("outgoing"),
        'connected': _("connected"),
        'ended': _("ended"),
    }.get(call.state, call.state)
    peer = call.peer or _("Unknown")
    return _("{kind} with {peer}: {state}").format(kind=kind, peer=peer, state=state)


def _safe_name(name: str, fallback: str) -> str:
    cleaned = ''.join(ch for ch in (name or '') if ch.isalnum() or ch in ' ._-()[]')
    cleaned = cleaned.strip() or f"{fallback}.bin"
    return cleaned[:120]


def _guess_mime(path: str) -> str:
    import mimetypes
    guessed, _unused = mimetypes.guess_type(path)
    return guessed or 'application/octet-stream'
