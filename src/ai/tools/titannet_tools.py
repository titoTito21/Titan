"""Titan-Net for the AI: forum posts, mail, groups, rooms and private messages.

``TitanNetClient`` is already a complete, synchronous, in-process API, so
nothing here reimplements the protocol - these are thin, well-described wrappers
whose real work is turning ``{'success': False, 'error': ...}`` into a sentence
the AI can act on, and refusing to guess when the user is not signed in.

Everything that publishes - a topic, a reply, a message, mail - is
``always_confirm``: the user sees the exact text before it leaves the machine,
because a post cannot be recalled.
"""

import threading

from src.ai.titan_tools import _titan_net_client

_signin_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Shared plumbing
# --------------------------------------------------------------------------- #
def saved_credentials():
    """(username, password) the user asked Titan to remember, or ('', '').

    Titan-Net's own login screen stores these in the encrypted ``titan.IM``
    file when "log me in automatically" is ticked. A user who ticked it has
    signed in; being told to go and open a window to do it again is Titan
    forgetting something it was told.
    """
    try:
        from src.settings.titan_im_config import load_titan_im_config
        config = load_titan_im_config() or {}
    except Exception:
        return '', ''
    return (str(config.get('titannet_username') or '').strip(),
            str(config.get('titannet_password') or ''))


def _sign_in_with_saved():
    """(client, error_text) - sign in headlessly with the saved credentials."""
    username, password = saved_credentials()
    if not (username and password):
        return None, ''
    with _signin_lock:
        client = _titan_net_client()
        if client is not None and getattr(client, 'username', None):
            return client, ''
        # A client built here is NOT published until the sign-in works.
        # get_active_titan_net_client() is what every frontend reads, so
        # registering a client that then failed to log in would leave the whole
        # program holding a dead one.
        fresh = client is None
        try:
            if fresh:
                from src.network.titan_net import TitanNetClient
                client = TitanNetClient()
            result = client.login(username, password)
        except Exception as e:
            return None, f"Could not sign in to Titan-Net as {username}: {e}"
        if isinstance(result, dict) and not result.get('success'):
            detail = result.get('message') or result.get('error') or 'refused'
            return None, (f"Titan-Net refused the saved sign-in for "
                          f"{username}: {detail}")
        try:
            from src.network.titan_net import (
                register_active_titan_net_client, set_active_titan_logged_in)
            if fresh:
                register_active_titan_net_client(client)
            set_active_titan_logged_in(True)
        except Exception:
            pass
        return client, ''


def _client():
    """(client, error_text). Never raises."""
    client = _titan_net_client()
    if client is not None and getattr(client, 'username', None):
        return client, ''
    signed_in, error = _sign_in_with_saved()
    if signed_in is not None:
        return signed_in, ''
    if error:
        return None, error
    if client is None:
        return None, ("Titan-Net is not open and no sign-in is saved. Open it "
                      "in Titan once, ticking 'log me in automatically', or "
                      "sign in with titan_im_login.")
    return None, ("Nobody is signed in to Titan-Net and no sign-in is saved. "
                  "Sign in with titan_im_login (service 'titan_net'), or open "
                  "the Titan-Net view once with 'log me in automatically' "
                  "ticked.")


def _failed(result, what):
    """The error sentence for a call that did not succeed, or '' when it did."""
    if isinstance(result, dict) and result.get('success'):
        return ''
    detail = ''
    if isinstance(result, dict):
        detail = str(result.get('error') or result.get('message') or '')
    return f"{what} failed{': ' + detail if detail else '.'}"


def _clip(text, limit=600):
    text = str(text or '').strip()
    return text if len(text) <= limit else text[:limit].rstrip() + '...'


def _lines(items, render, empty):
    if not items:
        return empty
    return "\n".join(render(item) for item in items)


# --------------------------------------------------------------------------- #
# Who am I
# --------------------------------------------------------------------------- #
def titannet_status(**_):
    """Whether Titan-Net is connected and who is signed in."""
    client, error = _client()
    if client is None:
        return error
    role = ''
    try:
        result = client.get_user_role()
        if isinstance(result, dict) and result.get('success'):
            role = str(result.get('role') or '')
    except Exception:
        pass
    return (f"Signed in to Titan-Net as {client.username}"
            f" (id {getattr(client, 'user_id', '?')})"
            f"{', role ' + role if role else ''}.")


# --------------------------------------------------------------------------- #
# Forum
# --------------------------------------------------------------------------- #
def titannet_list_topics(category="", forum_id="", limit=25, **_):
    """List forum topics, newest first."""
    client, error = _client()
    if error:
        return error
    try:
        result = client.get_forum_topics(
            category=category or None,
            limit=int(limit or 25),
            forum_id=int(forum_id) if str(forum_id).strip() else None)
    except Exception as e:
        return f"Could not read the forum: {e}"
    failure = _failed(result, "Reading the forum")
    if failure:
        return failure
    topics = result.get('topics') or []
    return _lines(
        topics,
        lambda t: (f"#{t.get('id')} {t.get('title')} - by "
                   f"{t.get('author') or t.get('username') or '?'}, "
                   f"{t.get('reply_count', 0)} replies"
                   f"{' [pinned]' if t.get('pinned') else ''}"
                   f"{' [locked]' if t.get('locked') else ''}"),
        "There are no topics here yet.")


def titannet_read_topic(topic_id, **_):
    """Read one topic and its replies."""
    client, error = _client()
    if error:
        return error
    try:
        topic = client.get_forum_topic(int(topic_id))
        replies = client.get_forum_replies(int(topic_id), limit=100)
    except Exception as e:
        return f"Could not read topic {topic_id}: {e}"
    failure = _failed(topic, f"Reading topic {topic_id}")
    if failure:
        return failure
    data = topic.get('topic') or topic
    out = [f"#{data.get('id')} {data.get('title')}",
           f"by {data.get('author') or data.get('username') or '?'}"
           f" - {data.get('created_at', '')}",
           "",
           _clip(data.get('content'), 4000),
           ""]
    items = (replies.get('replies') or []) if isinstance(replies, dict) else []
    out.append(f"{len(items)} replies:")
    for reply in items:
        out.append(f"- {reply.get('author') or reply.get('username') or '?'}: "
                   f"{_clip(reply.get('content'), 800)}")
    return "\n".join(out)


def titannet_post_topic(title, content, category="general", forum_id="", **_):
    """Start a new forum topic."""
    client, error = _client()
    if error:
        return error
    if not str(title).strip() or not str(content).strip():
        return "A topic needs both a title and some content."
    try:
        result = client.create_forum_topic(
            title=title, content=content, category=category or 'general',
            forum_id=int(forum_id) if str(forum_id).strip() else None)
    except Exception as e:
        return f"Could not post the topic: {e}"
    failure = _failed(result, "Posting the topic")
    if failure:
        return failure
    return (f"Posted '{title}' to the Titan-Net forum "
            f"(topic #{result.get('topic_id', '?')}).")


def titannet_reply(topic_id, content, **_):
    """Reply to a forum topic."""
    client, error = _client()
    if error:
        return error
    if not str(content).strip():
        return "A reply needs some text."
    try:
        result = client.add_forum_reply(int(topic_id), content)
    except Exception as e:
        return f"Could not post the reply: {e}"
    failure = _failed(result, "Posting the reply")
    if failure:
        return failure
    return f"Replied to topic #{topic_id}."


def titannet_search_forum(query, limit=25, **_):
    """Search the forum."""
    client, error = _client()
    if error:
        return error
    try:
        result = client.search_forum(query, limit=int(limit or 25))
    except Exception as e:
        return f"The forum search failed: {e}"
    failure = _failed(result, "Searching the forum")
    if failure:
        return failure
    return _lines(result.get('topics') or [],
                  lambda t: f"#{t.get('id')} {t.get('title')}",
                  f"Nothing on the forum matches '{query}'.")


def titannet_whats_new(**_):
    """What has appeared on Titan-Net since the user last looked."""
    client, error = _client()
    if error:
        return error
    try:
        result = client.get_whats_new()
    except Exception as e:
        return f"Could not check what is new: {e}"
    failure = _failed(result, "Checking what is new")
    if failure:
        return failure
    topics = result.get('topics') or result.get('items') or []
    return _lines(topics,
                  lambda t: (f"#{t.get('id')} {t.get('title')} - "
                             f"{t.get('unread_count', t.get('reply_count', 0))} new"),
                  "Nothing new on the forum.")


# --------------------------------------------------------------------------- #
# Groups
# --------------------------------------------------------------------------- #
def titannet_list_groups(**_):
    """List Titan-Net groups."""
    client, error = _client()
    if error:
        return error
    try:
        result = client.list_groups()
    except Exception as e:
        return f"Could not list the groups: {e}"
    failure = _failed(result, "Listing the groups")
    if failure:
        return failure
    return _lines(
        result.get('groups') or [],
        lambda g: (f"#{g.get('id')} {g.get('name')} "
                   f"({g.get('visibility', 'public')}, "
                   f"{g.get('member_count', 0)} members)"
                   f"{' - you are a member' if g.get('is_member') else ''}"),
        "There are no groups yet.")


def titannet_group_forums(group_id, **_):
    """List the forums inside one group, so a topic can be posted in the right
    place."""
    client, error = _client()
    if error:
        return error
    try:
        result = client.get_group(int(group_id))
    except Exception as e:
        return f"Could not read group {group_id}: {e}"
    failure = _failed(result, f"Reading group {group_id}")
    if failure:
        return failure
    group = result.get('group') or result
    forums = group.get('forums') or []
    header = f"{group.get('name')} - {_clip(group.get('description'), 200)}"
    return header + "\n" + _lines(
        forums, lambda f: f"  forum #{f.get('id')} {f.get('name')}",
        "  (this group has no forums)")


def titannet_join_group(group_id, **_):
    """Join a Titan-Net group."""
    client, error = _client()
    if error:
        return error
    try:
        result = client.join_group(int(group_id))
    except Exception as e:
        return f"Could not join group {group_id}: {e}"
    failure = _failed(result, f"Joining group {group_id}")
    return failure or f"Joined group #{group_id}."


# --------------------------------------------------------------------------- #
# Mail
# --------------------------------------------------------------------------- #
_FORMATS = {'text': 'plain', 'plain': 'plain', 'txt': 'plain',
            'markdown': 'markdown', 'md': 'markdown',
            'html': 'html'}


# The mail API names its fields from_addr / to_addr / received_at. Reading
# 'from' and 'created_at' produced a listing where every message came from '?'
# at no particular time, which is worse than no listing at all.
def _addr(mail, *names):
    for name in names:
        value = mail.get(name)
        if value:
            return str(value)
    return ''


def _sender(mail):
    return _addr(mail, 'from_addr', 'from', 'sender') or '?'


def _recipient(mail):
    return _addr(mail, 'to_addr', 'to', 'recipient') or '?'


def _peer(mail):
    """Whoever is not the user: the sender in, the recipient out."""
    if str(mail.get('direction', '')).lower() == 'out' or \
            str(mail.get('folder', '')).lower() == 'sent':
        return _recipient(mail)
    return _sender(mail)


def _when(mail):
    return _addr(mail, 'received_at', 'created_at', 'sent_at', 'date')


def _mailbox(client, folder):
    """(messages, error). 'unread' is the inbox, filtered."""
    wanted = str(folder or 'inbox').strip().lower()
    remote = 'sent' if wanted.startswith('s') else 'inbox'
    try:
        result = client.get_mailbox(remote)
    except Exception as e:
        return None, f"Could not open the mailbox: {e}"
    failure = _failed(result, "Opening the mailbox")
    if failure:
        return None, failure
    messages = result.get('messages') or result.get('mail') or []
    if wanted.startswith('u'):
        messages = [m for m in messages if not m.get('read')]
    return messages, ''


def titannet_mail_address(**_):
    """The user's own Titan Mail address, and how much is waiting."""
    client, error = _client()
    if error:
        return error
    address = ''
    try:
        result = client.get_mailbox('inbox')
        if isinstance(result, dict):
            address = str(result.get('address') or '')
    except Exception:
        result = None
    if not address:
        # The server says what the address is; this is only for a server too
        # old to answer, and it must still name the server actually in use
        # rather than a domain written into the client.
        host = getattr(client, 'server_host', '') or 'titosofttitan.com'
        address = f"{getattr(client, 'username', '?')}@{host}"
    messages = []
    if isinstance(result, dict):
        messages = result.get('messages') or result.get('mail') or []
    unread = len([m for m in messages if not m.get('read')])
    return (f"The user's Titan Mail address is {address}. "
            f"{len(messages)} messages in the inbox, {unread} unread.")


def titannet_list_mail(folder="inbox", **_):
    """List the user's Titan Mail."""
    client, error = _client()
    if error:
        return error
    messages, error = _mailbox(client, folder)
    if error:
        return error
    return _lines(
        messages,
        lambda m: (f"#{m.get('id')} {'[unread] ' if not m.get('read') else ''}"
                   f"{m.get('subject') or '(no subject)'} - "
                   f"{_peer(m)} - {_when(m)}"),
        "There is nothing in that folder.")


def _fetch_mail(client, mail_id):
    """(mail dict, error)."""
    try:
        result = client.get_mail(int(mail_id))
    except (TypeError, ValueError):
        return None, f"'{mail_id}' is not a message number."
    except Exception as e:
        return None, f"Could not read message {mail_id}: {e}"
    failure = _failed(result, f"Reading message {mail_id}")
    if failure:
        return None, failure
    return (result.get('mail') or result.get('message') or result), ''


def titannet_read_mail(mail_id, **_):
    """Read one message. This marks it as read."""
    client, error = _client()
    if error:
        return error
    mail, error = _fetch_mail(client, mail_id)
    if error:
        return error
    # A message may have been written as Markdown or HTML. Reading the raw
    # body would hand the AI a wall of tags; the Mail client already knows how
    # to reduce either to the text a person would hear, so it does that here
    # too - one renderer, the same reading.
    body = mail.get('body') or ''
    try:
        from src.network import mail_format
        body = mail_format.to_plain_text(body,
                                         mail.get('content_type', ''),
                                         mail.get('body_html', '') or '')
    except Exception:
        pass
    return (f"From: {_sender(mail)}\n"
            f"To: {_recipient(mail)}\n"
            f"Subject: {mail.get('subject') or '(no subject)'}\n"
            f"Date: {_when(mail)}\n\n"
            f"{_clip(body, 6000)}")


def _send(client, to, subject, body, fmt):
    """Send one message, with the HTML alternative the format calls for."""
    payload = {'body': body, 'body_html': '', 'content_type': 'text/plain'}
    try:
        from src.network import mail_format
        payload = mail_format.build_outgoing(body, _FORMATS.get(fmt, 'plain'))
    except Exception:
        pass
    try:
        result = client.send_mail(to_addr=to,
                                  subject=subject or '(no subject)',
                                  body=payload.get('body', body),
                                  body_html=payload.get('body_html', ''),
                                  content_type=payload.get('content_type',
                                                           'text/plain'))
    except Exception as e:
        return f"Could not send the mail: {e}"
    return _failed(result, "Sending the mail")


def titannet_send_mail(to, subject, body, format="text", **_):
    """Send mail from the user's Titan Mail address."""
    client, error = _client()
    if error:
        return error
    if not str(to).strip() or not str(body).strip():
        return "Mail needs a recipient and a body."
    kind = str(format or 'text').strip().lower()
    if kind not in _FORMATS:
        return ("A message is written as 'text', 'markdown' or 'html'.")
    failure = _send(client, to, subject, body, kind)
    return failure or f"Sent mail to {to} ('{subject or '(no subject)'}')."


def titannet_reply_mail(mail_id, body, format="text", quote=True, **_):
    """Reply to a message, to its sender, with its subject."""
    client, error = _client()
    if error:
        return error
    if not str(body).strip():
        return "A reply needs something to say."
    mail, error = _fetch_mail(client, mail_id)
    if error:
        return error
    to = _addr(mail, 'from_addr', 'from', 'sender').strip()
    if not to:
        return f"Message {mail_id} has no sender to reply to."
    subject = str(mail.get('subject') or '').strip()
    if not subject.lower().startswith('re:'):
        subject = f"Re: {subject}" if subject else "Re:"
    text = body
    if str(quote).strip().lower() not in ('0', 'false', 'no', 'off'):
        try:
            from src.network import mail_format
            text = body + mail_format.quote_body(
                mail.get('body') or '', mail.get('content_type', ''),
                mail.get('body_html', '') or '', author=to)
        except Exception:
            pass
    kind = str(format or 'text').strip().lower()
    if kind not in _FORMATS:
        return "A message is written as 'text', 'markdown' or 'html'."
    failure = _send(client, to, subject, text, kind)
    return failure or f"Replied to {to} ('{subject}')."


def titannet_delete_mail(mail_id, **_):
    """Delete one message from the user's mailbox."""
    client, error = _client()
    if error:
        return error
    try:
        result = client.delete_mail(int(mail_id))
    except (TypeError, ValueError):
        return f"'{mail_id}' is not a message number."
    except Exception as e:
        return f"Could not delete message {mail_id}: {e}"
    failure = _failed(result, f"Deleting message {mail_id}")
    return failure or f"Deleted message {mail_id}."


# --------------------------------------------------------------------------- #
# Rooms and people
# --------------------------------------------------------------------------- #
def titannet_list_rooms(**_):
    """List Titan-Net chat rooms."""
    client, error = _client()
    if error:
        return error
    try:
        result = client.get_rooms()
    except Exception as e:
        return f"Could not list the rooms: {e}"
    failure = _failed(result, "Listing the rooms")
    if failure:
        return failure
    return _lines(result.get('rooms') or [],
                  lambda r: (f"#{r.get('id')} {r.get('name')} "
                             f"({r.get('type', 'text')}"
                             f"{', password' if r.get('has_password') else ''})"),
                  "There are no rooms.")


def titannet_send_room_message(room_id, message, **_):
    """Say something in a Titan-Net room."""
    client, error = _client()
    if error:
        return error
    try:
        result = client.send_room_message(int(room_id), message)
    except Exception as e:
        return f"Could not send to room {room_id}: {e}"
    failure = _failed(result, f"Sending to room {room_id}")
    return failure or f"Sent to room #{room_id}."


def titannet_read_room(room_id, limit=30, **_):
    """Read what has been said in a room."""
    client, error = _client()
    if error:
        return error
    try:
        result = client.get_room_messages(int(room_id), limit=int(limit or 30))
    except Exception as e:
        return f"Could not read room {room_id}: {e}"
    failure = _failed(result, f"Reading room {room_id}")
    if failure:
        return failure
    return _lines(result.get('messages') or [],
                  lambda m: (f"{m.get('username') or m.get('sender') or '?'}: "
                             f"{_clip(m.get('message') or m.get('content'), 400)}"),
                  "Nothing has been said in this room.")


def titannet_read_private(username, limit=30, **_):
    """Read the private conversation with one person."""
    client, error = _client()
    if error:
        return error
    try:
        from src.ai.titan_tools import _titan_net_resolve_recipient
        user_id, resolve_error = _titan_net_resolve_recipient(client, username)
        if not user_id:
            return resolve_error or f"There is no Titan-Net user '{username}'."
        result = client.get_private_messages(user_id, limit=int(limit or 30))
    except Exception as e:
        return f"Could not read the conversation: {e}"
    failure = _failed(result, f"Reading the conversation with {username}")
    if failure:
        return failure
    return _lines(result.get('messages') or [],
                  lambda m: (f"{m.get('sender') or m.get('username') or '?'}: "
                             f"{_clip(m.get('message') or m.get('content'), 400)}"),
                  f"No messages with {username} yet.")


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
def get_titannet_tools():
    from src.ai.agent_tools import _tool
    S = {'type': 'string'}
    N = {'type': 'number'}
    return [
        _tool('titannet_status',
              "Check whether Titan-Net is connected and who is signed in. Do "
              "this before anything else on Titan-Net.", titannet_status),
        # Forum
        _tool('titannet_list_topics',
              "List Titan-Net forum topics, newest first. Without a forum_id "
              "this is the main forum; with one, that group's forum.",
              titannet_list_topics,
              properties={'category': dict(S, description="Category filter (optional)."),
                          'forum_id': dict(S, description="Group forum id (optional)."),
                          'limit': dict(N, description="How many (default 25).")}),
        _tool('titannet_read_topic',
              "Read one Titan-Net forum topic together with its replies.",
              titannet_read_topic,
              properties={'topic_id': dict(N, description="Topic id.")},
              required=['topic_id']),
        _tool('titannet_search_forum', "Search the Titan-Net forum.",
              titannet_search_forum,
              properties={'query': dict(S, description="What to look for."),
                          'limit': dict(N, description="How many (default 25).")},
              required=['query']),
        _tool('titannet_whats_new',
              "What is new on the Titan-Net forum since the user last looked.",
              titannet_whats_new),
        _tool('titannet_post_topic',
              "Publish a new topic on the Titan-Net forum. Everyone can read "
              "it and it cannot be unpublished, so show the user the text "
              "first.", titannet_post_topic,
              risk='confirm', always_confirm=True,
              properties={'title': dict(S, description="Topic title."),
                          'content': dict(S, description="The post itself."),
                          'category': dict(S, description="Category (default 'general')."),
                          'forum_id': dict(S, description="Post inside this group forum (optional).")},
              required=['title', 'content']),
        _tool('titannet_reply',
              "Publish a reply to a Titan-Net forum topic.", titannet_reply,
              risk='confirm', always_confirm=True,
              properties={'topic_id': dict(N, description="Topic to reply to."),
                          'content': dict(S, description="The reply text.")},
              required=['topic_id', 'content']),
        # Groups
        _tool('titannet_list_groups', "List Titan-Net groups.",
              titannet_list_groups),
        _tool('titannet_group_forums',
              "List the forums in one Titan-Net group, so a topic can be "
              "posted in the right one.", titannet_group_forums,
              properties={'group_id': dict(N, description="Group id.")},
              required=['group_id']),
        _tool('titannet_join_group', "Join a Titan-Net group.",
              titannet_join_group, risk='confirm',
              properties={'group_id': dict(N, description="Group id.")},
              required=['group_id']),
        # Mail
        _tool('titannet_mail_address',
              "The user's own Titan Mail address, and how much mail is "
              "waiting. Use this when the user asks what their address is, or "
              "whether they have new mail.",
              titannet_mail_address),
        _tool('titannet_list_mail',
              "List the user's Titan Mail (folder 'inbox', 'unread' or 'sent').",
              titannet_list_mail,
              properties={'folder': dict(S, description="'inbox' (default), "
                                         "'unread' or 'sent'.")}),
        _tool('titannet_read_mail',
              "Read one Titan Mail message. This marks it as read.",
              titannet_read_mail,
              properties={'mail_id': dict(N, description="Message id.")},
              required=['mail_id']),
        _tool('titannet_send_mail',
              "Send an e-mail from the user's Titan Mail address. Works for "
              "Titan-Net users and for ordinary outside addresses. Show the "
              "user the text before sending.", titannet_send_mail,
              risk='confirm', always_confirm=True,
              properties={'to': dict(S, description="Recipient address."),
                          'subject': dict(S, description="Subject line."),
                          'body': dict(S, description="The message, as readable plain text."),
                          'format': dict(S, description="'text' (default), "
                                         "'markdown' or 'html'. Markdown and "
                                         "HTML are sent with a plain-text "
                                         "alternative, so every mail program "
                                         "can read them.")},
              required=['to', 'body']),
        _tool('titannet_reply_mail',
              "Reply to a Titan Mail message - to its sender, with its "
              "subject, quoting it. Show the user the text before sending.",
              titannet_reply_mail, risk='confirm', always_confirm=True,
              properties={'mail_id': dict(N, description="The message being replied to."),
                          'body': dict(S, description="The reply."),
                          'format': dict(S, description="'text' (default), 'markdown' or 'html'."),
                          'quote': {'type': 'boolean',
                                    'description': "Quote the original below "
                                                   "the reply (default true)."}},
              required=['mail_id', 'body']),
        _tool('titannet_delete_mail',
              "Delete one message from the user's Titan Mail.",
              titannet_delete_mail, risk='confirm', always_confirm=True,
              properties={'mail_id': dict(N, description="Message id.")},
              required=['mail_id']),
        # Rooms and people
        _tool('titannet_list_rooms', "List Titan-Net chat rooms.",
              titannet_list_rooms),
        _tool('titannet_read_room', "Read recent messages in a Titan-Net room.",
              titannet_read_room,
              properties={'room_id': dict(N, description="Room id."),
                          'limit': dict(N, description="How many (default 30).")},
              required=['room_id']),
        _tool('titannet_send_room_message',
              "Say something in a Titan-Net room. Everyone in the room sees it.",
              titannet_send_room_message, risk='confirm', always_confirm=True,
              properties={'room_id': dict(N, description="Room id."),
                          'message': dict(S, description="What to say.")},
              required=['room_id', 'message']),
        _tool('titannet_read_private',
              "Read the private conversation with one Titan-Net user.",
              titannet_read_private,
              properties={'username': dict(S, description="Their username."),
                          'limit': dict(N, description="How many (default 30).")},
              required=['username']),
    ]
