"""Elten for the AI - private messages, forums and blogs.

Elten is a separate community with its own protocol, and Titan already speaks
it (``src/eltenlink_client/elten_client.py``). Unlike Titan-Net there is no
long-lived client object to borrow: the GUI builds one when the user opens the
Elten window. So these tools build their own and sign it in with the
credentials the user already saved in the encrypted ``titan.IM`` file - and if
nothing is saved, they say so instead of asking the AI to invent a password.

The client is cached for the life of the Titan process, because Elten's token
is per-session and re-logging in for every tool call would be rude to the
server.
"""

import threading

_client = None
_lock = threading.Lock()


def _get_client():
    """(client, error_text)."""
    global _client
    with _lock:
        if _client is not None and getattr(_client, 'token', None):
            return _client, ''
        try:
            from src.eltenlink_client.elten_client import EltenLinkClient
            from src.settings.titan_im_config import get_eltenlink_credentials
        except Exception as e:
            return None, f"Elten support is not available: {e}"
        try:
            username, token, password = get_eltenlink_credentials()
        except Exception:
            username = token = password = None
        if not username or not (token or password):
            return None, ("Nobody is signed in to Elten. Open Elten in Titan "
                          "and sign in once - Titan remembers it after that.")
        client = EltenLinkClient()
        client.username = username
        client.token = token
        if password:
            client.password = password
        try:
            if not client.check_token():
                if not password:
                    return None, ("The saved Elten session has expired. Open "
                                  "Elten in Titan and sign in again.")
                result = client.login(username, password)
                if not (isinstance(result, dict) and result.get('success', True)):
                    return None, ("Could not sign in to Elten: "
                                  + str(result.get('error', 'refused')))
        except Exception as e:
            return None, f"Could not reach Elten: {e}"
        _client = client
        return client, ''


def _clip(text, limit=600):
    text = str(text or '').strip()
    return text if len(text) <= limit else text[:limit].rstrip() + '...'


def _listing(items, render, empty):
    if not items:
        return empty
    return "\n".join(render(item) for item in items)


def _field(item, *names, default=''):
    """Elten's client returns dicts whose keys differ between endpoints."""
    if isinstance(item, dict):
        for name in names:
            if item.get(name) not in (None, ''):
                return item[name]
    else:
        for name in names:
            value = getattr(item, name, None)
            if value not in (None, ''):
                return value
    return default


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def elten_status(**_):
    """Whether Titan can act on Elten, and as whom."""
    client, error = _get_client()
    if error:
        return error
    return f"Signed in to Elten as {client.username}."


def elten_list_conversations(**_):
    """List Elten private conversations."""
    client, error = _get_client()
    if error:
        return error
    try:
        conversations = client.get_conversations()
    except Exception as e:
        return f"Could not read the Elten conversations: {e}"
    return _listing(
        conversations,
        lambda c: (f"- {_field(c, 'user', 'name', default='?')}"
                   f"{' [unread]' if _field(c, 'unread', default=0) else ''}"
                   f" - {_clip(_field(c, 'subject', 'last_subject'), 80)}"),
        "There are no Elten conversations.")


def elten_read_conversation(user, subject="", **_):
    """Read the messages of one Elten conversation."""
    client, error = _get_client()
    if error:
        return error
    try:
        messages = client.get_conversation_messages(user, subject=subject or "")
    except Exception as e:
        return f"Could not read the conversation with {user}: {e}"
    return _listing(
        messages,
        lambda m: (f"{_field(m, 'user', 'author', 'from', default='?')}: "
                   f"{_clip(_field(m, 'text', 'body', 'content'), 800)}"),
        f"No messages with {user}.")


def elten_send_message(to, subject, text, **_):
    """Send an Elten private message."""
    client, error = _get_client()
    if error:
        return error
    if not str(text).strip():
        return "There is nothing to send."
    try:
        result = client.send_message(to, subject or '', text)
    except Exception as e:
        return f"Could not send the Elten message: {e}"
    if isinstance(result, dict) and not result.get('success', True):
        return f"Elten refused the message: {result.get('error', 'unknown')}"
    return f"Sent an Elten message to {to}."


def elten_list_forums(group_id="", **_):
    """List Elten forum groups, or the forums inside one group."""
    client, error = _get_client()
    if error:
        return error
    try:
        if str(group_id).strip():
            forums = client.get_forums_in_group(int(group_id))
            return _listing(
                forums,
                lambda f: (f"- forum {_field(f, 'id', default='?')}: "
                           f"{_field(f, 'name', 'title', default='?')}"),
                "This group has no forums.")
        groups = client.get_forum_groups()
    except Exception as e:
        return f"Could not read the Elten forums: {e}"
    return _listing(
        groups,
        lambda g: (f"- group {_field(g, 'id', default='?')}: "
                   f"{_field(g, 'name', 'title', default='?')}"),
        "There are no Elten forum groups.")


def elten_list_threads(forum_id, **_):
    """List the threads of an Elten forum."""
    client, error = _get_client()
    if error:
        return error
    try:
        threads = client.get_threads_in_forum(int(forum_id))
    except Exception as e:
        return f"Could not read forum {forum_id}: {e}"
    return _listing(
        threads,
        lambda t: (f"- thread {_field(t, 'id', default='?')}: "
                   f"{_field(t, 'name', 'title', 'subject', default='?')}"),
        "This forum has no threads.")


def elten_read_thread(thread_id, **_):
    """Read the posts of an Elten thread."""
    client, error = _get_client()
    if error:
        return error
    try:
        posts = client.get_thread_posts(int(thread_id))
    except Exception as e:
        return f"Could not read thread {thread_id}: {e}"
    return _listing(
        posts,
        lambda p: (f"{_field(p, 'user', 'author', default='?')}: "
                   f"{_clip(_field(p, 'text', 'content', 'body'), 800)}"),
        "This thread has no posts.")


def elten_search_forum(query, **_):
    """Search the Elten forums."""
    client, error = _get_client()
    if error:
        return error
    try:
        results = client.search_forum(query)
    except Exception as e:
        return f"The Elten search failed: {e}"
    return _listing(
        results,
        lambda r: (f"- {_field(r, 'name', 'title', 'subject', default='?')} "
                   f"(thread {_field(r, 'id', default='?')})"),
        f"Nothing on Elten matches '{query}'.")


def elten_online_users(**_):
    """Who is on Elten right now."""
    client, error = _get_client()
    if error:
        return error
    try:
        users = client.get_online_users()
    except Exception as e:
        return f"Could not read who is online: {e}"
    names = [str(_field(u, 'name', 'user', default=u)) for u in (users or [])]
    return ("Online on Elten: " + ", ".join(names)) if names else \
        "Nobody is showing as online on Elten."


def elten_set_status(text, **_):
    """Set the user's Elten status text."""
    client, error = _get_client()
    if error:
        return error
    try:
        client.set_status(text or '')
    except Exception as e:
        return f"Could not set the Elten status: {e}"
    return f"Elten status set to '{text}'." if text else "Elten status cleared."


def get_elten_tools():
    from src.ai.agent_tools import _tool
    S = {'type': 'string'}
    N = {'type': 'number'}
    return [
        _tool('elten_status',
              "Check whether Titan can act on Elten and as whom. Do this "
              "before the other elten_ tools.", elten_status),
        _tool('elten_list_conversations',
              "List the user's Elten private conversations.",
              elten_list_conversations),
        _tool('elten_read_conversation',
              "Read one Elten private conversation.", elten_read_conversation,
              properties={'user': dict(S, description="The other person's Elten name."),
                          'subject': dict(S, description="A particular subject (optional).")},
              required=['user']),
        _tool('elten_send_message',
              "Send an Elten private message. It goes to a real person, so "
              "show the user the text first.", elten_send_message,
              risk='confirm', always_confirm=True,
              properties={'to': dict(S, description="Recipient's Elten name."),
                          'subject': dict(S, description="Subject line."),
                          'text': dict(S, description="The message.")},
              required=['to', 'text']),
        _tool('elten_list_forums',
              "List Elten forum groups, or the forums inside one group.",
              elten_list_forums,
              properties={'group_id': dict(S, description="Group id, to list its forums (optional).")}),
        _tool('elten_list_threads', "List the threads of an Elten forum.",
              elten_list_threads,
              properties={'forum_id': dict(N, description="Forum id.")},
              required=['forum_id']),
        _tool('elten_read_thread', "Read the posts of an Elten thread.",
              elten_read_thread,
              properties={'thread_id': dict(N, description="Thread id.")},
              required=['thread_id']),
        _tool('elten_search_forum', "Search the Elten forums.",
              elten_search_forum,
              properties={'query': dict(S, description="What to look for.")},
              required=['query']),
        _tool('elten_online_users', "Who is on Elten right now.",
              elten_online_users),
        _tool('elten_set_status', "Set the user's Elten status text.",
              elten_set_status, risk='confirm',
              properties={'text': dict(S, description="The status text.")},
              required=['text']),
    ]
