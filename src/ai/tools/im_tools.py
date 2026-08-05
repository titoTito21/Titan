"""Titan IM for the AI - one bridge for every web-backed messenger.

``IMBackend`` (src/network/im_web/base.py) is already a service-agnostic command
set with a capability list, which is the whole reason this module is short:
WhatsApp and Messenger differ enormously underneath and not at all here, and a
messenger added later works through the same tools without touching this file.

Two rules the code enforces rather than documents:

- **The engine is never started on the AI's behalf.** ``get_*_backend(start=
  False)`` is deliberate: an AI must not silently open a WhatsApp session the
  user never asked for. If the client is not open, the tools say so.
- **Capabilities gate everything.** The live page reports what it can actually
  do; asking for a reaction on a service that cannot react gets a clear
  sentence instead of a timeout.
"""

import threading

from src.ai.titan_tools import _norm_service, _im_backend

_TIMEOUT = 30.0


# --------------------------------------------------------------------------- #
# Plumbing
# --------------------------------------------------------------------------- #
def _backend(service):
    """(backend, error_text)."""
    svc = _norm_service(service)
    if svc not in ('whatsapp', 'messenger'):
        return None, (f"'{service}' is not a web-backed Titan IM service. "
                      f"These tools cover 'whatsapp' and 'messenger'; use "
                      f"titan_send_message for Titan-Net and Telegram.")
    try:
        backend = _im_backend(svc)
    except Exception as e:
        return None, f"Could not reach the {svc} client: {e}"
    if backend is None or not backend.running:
        return None, (f"The {svc} client is not open. Open it in Titan first "
                      f"(Titan IM), then try again.")
    if not backend.logged_in:
        return None, (f"The {svc} client is open but not signed in. The user "
                      f"has to sign in first.")
    return backend, ''


def _await(call, timeout=_TIMEOUT):
    """Run one asynchronous backend command and wait for its result."""
    done = threading.Event()
    box = {}

    def callback(result):
        box.update(result or {})
        done.set()

    try:
        call(callback)
    except Exception as e:
        return {'success': False, 'error': str(e)}
    if not done.wait(timeout):
        return {'success': False, 'error': 'the page did not answer in time'}
    return box


def _needs(backend, capability, what):
    if backend.has(capability):
        return ''
    return (f"This service cannot {what} (the page does not offer it). "
            f"It can: {', '.join(sorted(backend.capabilities)) or 'very little'}.")


def _resolve_chat(backend, chat):
    """A chat id from whatever the user called the conversation."""
    wanted = str(chat or '').strip()
    if not wanted:
        return '', "Say which conversation."
    if wanted in backend.chats:
        return wanted, ''
    lowered = wanted.lower()
    for chat_id, entry in backend.chats.items():
        if str(getattr(entry, 'name', '')).lower() == lowered:
            return chat_id, ''
    for chat_id, entry in backend.chats.items():
        if lowered in str(getattr(entry, 'name', '')).lower():
            return chat_id, ''
    result = _await(lambda cb: backend.list_chats('all', callback=cb))
    for entry in (result.get('chats') or []):
        name = str(getattr(entry, 'name', '') or
                   (entry.get('name') if isinstance(entry, dict) else ''))
        entry_id = getattr(entry, 'id', None) or (
            entry.get('id') if isinstance(entry, dict) else None)
        if entry_id and lowered in name.lower():
            return entry_id, ''
    return '', (f"No conversation called '{chat}'. Use im_list_chats to see "
                f"what is there.")


def _render_message(message):
    who = getattr(message, 'sender', None) or getattr(message, 'author', '') or '?'
    text = getattr(message, 'text', '') or ''
    when = getattr(message, 'timestamp', '') or ''
    if getattr(message, 'has_media', False):
        text = (text + ' [attachment]').strip()
    return f"{who}: {text}" + (f"  ({when})" if when else '')


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def im_status(service, **_):
    """Whether a Titan IM client is open, signed in and what it can do."""
    svc = _norm_service(service)
    try:
        backend = _im_backend(svc)
    except Exception as e:
        return f"Could not reach the {service} client: {e}"
    if backend is None:
        return (f"'{service}' is not a web-backed Titan IM service "
                f"(these tools cover WhatsApp and Messenger).")
    if not backend.running:
        return f"The {svc} client is not open."
    state = "signed in" if backend.logged_in else "not signed in"
    return (f"The {svc} client is open and {state}. "
            f"It can: {', '.join(sorted(backend.capabilities)) or 'nothing yet'}."
            + (f" Last error: {backend.last_error}" if backend.last_error else ""))


def im_list_chats(service, scope="all", **_):
    """List the conversations in a Titan IM client."""
    backend, error = _backend(service)
    if error:
        return error
    result = _await(lambda cb: backend.list_chats(scope or 'all', callback=cb))
    chats = result.get('chats') or []
    if not chats:
        return (f"No conversations came back"
                + (f": {result.get('error')}" if result.get('error') else "."))
    lines = []
    for chat in chats[:60]:
        name = getattr(chat, 'name', '') or '?'
        unread = getattr(chat, 'unread', 0) or 0
        last = getattr(chat, 'last_message', '') or ''
        lines.append(f"- {name}" + (f" [{unread} unread]" if unread else "")
                     + (f" - {last[:60]}" if last else ""))
    return "Conversations:\n" + "\n".join(lines)


def im_read_chat(service, chat, limit=30, **_):
    """Read the recent messages of one conversation."""
    backend, error = _backend(service)
    if error:
        return error
    chat_id, error = _resolve_chat(backend, chat)
    if error:
        return error
    result = _await(lambda cb: backend.load_history(
        chat_id, limit=int(limit or 30), callback=cb))
    messages = result.get('messages') or []
    if not messages:
        return (f"No messages came back for '{chat}'"
                + (f": {result.get('error')}" if result.get('error') else "."))
    return (f"Conversation with {chat}:\n"
            + "\n".join(_render_message(m) for m in messages[-int(limit or 30):]))


def im_send(service, chat, text, **_):
    """Send a message in a Titan IM conversation."""
    backend, error = _backend(service)
    if error:
        return error
    missing = _needs(backend, 'send_text', "send messages")
    if missing:
        return missing
    if not str(text).strip():
        return "There is nothing to send."
    chat_id, error = _resolve_chat(backend, chat)
    if error:
        return error
    result = _await(lambda cb: backend.send_text(chat_id, text, callback=cb))
    if not result.get('success', True) or result.get('error'):
        return f"Could not send it: {result.get('error') or 'unknown error'}"
    return f"Sent to {chat}."


def im_reply(service, chat, message_id, text, **_):
    """Reply to one specific message."""
    backend, error = _backend(service)
    if error:
        return error
    missing = _needs(backend, 'reply_to', "reply to a specific message")
    if missing:
        return missing
    chat_id, error = _resolve_chat(backend, chat)
    if error:
        return error
    result = _await(lambda cb: backend.reply_to(chat_id, message_id, text,
                                                callback=cb))
    if result.get('error'):
        return f"Could not reply: {result['error']}"
    return f"Replied in {chat}."


def im_react(service, chat, message_id, emoji, **_):
    """React to a message."""
    backend, error = _backend(service)
    if error:
        return error
    missing = _needs(backend, 'react', "react to messages")
    if missing:
        return missing
    chat_id, error = _resolve_chat(backend, chat)
    if error:
        return error
    result = _await(lambda cb: backend.react(chat_id, message_id, emoji,
                                             callback=cb))
    if result.get('error'):
        return f"Could not react: {result['error']}"
    return f"Reacted in {chat}."


def im_search(service, query, chat="", **_):
    """Search the messages of a Titan IM service."""
    backend, error = _backend(service)
    if error:
        return error
    missing = _needs(backend, 'search', "search messages")
    if missing:
        return missing
    chat_id = ''
    if chat:
        chat_id, error = _resolve_chat(backend, chat)
        if error:
            return error
    result = _await(lambda cb: backend.search(query, chat_id=chat_id, callback=cb))
    messages = result.get('messages') or result.get('results') or []
    if not messages:
        return f"Nothing matches '{query}'."
    return "Matches:\n" + "\n".join(_render_message(m) for m in messages[:30])


def im_list_participants(service, chat, **_):
    """Who is in a group conversation."""
    backend, error = _backend(service)
    if error:
        return error
    missing = _needs(backend, 'list_participants', "list who is in a group")
    if missing:
        return missing
    chat_id, error = _resolve_chat(backend, chat)
    if error:
        return error
    result = _await(lambda cb: backend.list_participants(chat_id, callback=cb))
    people = result.get('participants') or result.get('contacts') or []
    if not people:
        return f"No participants came back for '{chat}'."
    return f"In {chat}:\n" + "\n".join(
        f"- {getattr(p, 'name', None) or p}" for p in people)


def im_mark_read(service, chat, **_):
    """Mark a conversation as read."""
    backend, error = _backend(service)
    if error:
        return error
    chat_id, error = _resolve_chat(backend, chat)
    if error:
        return error
    _await(lambda cb: backend.mark_read(chat_id, callback=cb))
    return f"Marked {chat} as read."


def get_im_tools():
    from src.ai.agent_tools import _tool
    S = {'type': 'string'}
    N = {'type': 'number'}
    service = dict(S, description="'whatsapp' or 'messenger'.")
    chat = dict(S, description="The conversation, by name or id.")
    return [
        _tool('im_status',
              "Check whether a Titan IM client (WhatsApp, Messenger) is open, "
              "signed in, and what the live page can actually do. Do this "
              "before the other im_ tools.", im_status,
              properties={'service': service}, required=['service']),
        _tool('im_list_chats',
              "List the conversations in a Titan IM client, with unread counts.",
              im_list_chats,
              properties={'service': service,
                          'scope': dict(S, description="'all' (default), 'pm', "
                                        "'groups' or 'channels'.")},
              required=['service']),
        _tool('im_read_chat',
              "Read the recent messages of one Titan IM conversation.",
              im_read_chat,
              properties={'service': service, 'chat': chat,
                          'limit': dict(N, description="How many (default 30).")},
              required=['service', 'chat']),
        _tool('im_send',
              "Send a message in a Titan IM conversation (WhatsApp, "
              "Messenger). The message goes to a real person, so show the "
              "user the text first.", im_send,
              risk='confirm', always_confirm=True,
              properties={'service': service, 'chat': chat,
                          'text': dict(S, description="What to send.")},
              required=['service', 'chat', 'text']),
        _tool('im_reply',
              "Reply to one specific message in a conversation.", im_reply,
              risk='confirm', always_confirm=True,
              properties={'service': service, 'chat': chat,
                          'message_id': dict(S, description="Id of the message to reply to."),
                          'text': dict(S, description="The reply.")},
              required=['service', 'chat', 'message_id', 'text']),
        _tool('im_react', "React to a message with an emoji.", im_react,
              risk='confirm',
              properties={'service': service, 'chat': chat,
                          'message_id': dict(S, description="Id of the message."),
                          'emoji': dict(S, description="The reaction, e.g. a thumbs up.")},
              required=['service', 'chat', 'message_id', 'emoji']),
        _tool('im_search', "Search the messages of a Titan IM service.",
              im_search,
              properties={'service': service,
                          'query': dict(S, description="What to look for."),
                          'chat': dict(S, description="Search inside one conversation (optional).")},
              required=['service', 'query']),
        _tool('im_list_participants', "Who is in a group conversation.",
              im_list_participants,
              properties={'service': service, 'chat': chat},
              required=['service', 'chat']),
        _tool('im_mark_read', "Mark a Titan IM conversation as read.",
              im_mark_read, risk='confirm',
              properties={'service': service, 'chat': chat},
              required=['service', 'chat']),
    ]
