"""Titan-Net as data, so another program can be a Titan-Net client.

`src/ai/tools/titannet_tools.py` answers Titan-Net in SENTENCES, which is
right for a model and for a macro: "there are four rooms, General, Help..."
is what somebody wants read to them. It is the wrong shape for a window. A
client needs a row per room, a row per message, an id to send to - and
reducing records to prose and parsing them back is how a client breaks the
first time somebody names a room with a comma in it.

So these hand over what `src/network/titan_net.py` already answers, as JSON.
It is the SAME client and the same session: whoever is signed in to
Titan-Net in Titan is who these speak as, the sign-in is the one Titan
already saved, and no credential is anywhere near this file.

Everything here runs on Titan's GUI thread, because that is where in-process
actions run (`inproc.call`), and a Titan-Net call is a network round trip.
That is why there is nothing here that polls: a client built on this
refreshes when the user asks it to, and Titan's own interface is held for
one round trip when they do, rather than for one every few seconds.
"""

import json


def _client():
    """The signed-in Titan-Net client, or (None, why not). Never raises."""
    from src.ai.tools.titannet_tools import _client as signed_in
    return signed_in()


def _payload(result, keys):
    """The interesting part of one of the client's answers."""
    if not isinstance(result, dict):
        return {}
    out = {}
    for key in keys:
        if key in result:
            out[key] = result[key]
    return out


def _answer(result, keys, what):
    """JSON when the call worked, a sentence when it did not.

    A caller reading these is drawing a window, so a failure must not arrive
    as JSON that happens to be empty - it would show an empty room list for
    a server that is simply not reachable.
    """
    if not isinstance(result, dict) or not result.get('success'):
        detail = ''
        if isinstance(result, dict):
            detail = str(result.get('error') or result.get('message') or '')
        return f"{what} did not work." + (f" {detail}" if detail else '')
    return json.dumps(_payload(result, keys), ensure_ascii=False, default=str)


def _resolve_room(client, room):
    """A room by its id, or by its name - a window shows names."""
    text = str(room or '').strip()
    if not text:
        return None, "Say which room."
    if text.isdigit():
        return int(text), ''
    try:
        listing = client.get_rooms()
    except Exception as e:
        return None, f"Could not list the rooms: {e}"
    for entry in (listing.get('rooms') or []) if isinstance(listing, dict) else []:
        if str(entry.get('name') or '').strip().lower() == text.lower():
            return entry.get('id'), ''
    return None, f"There is no Titan-Net room called '{room}'."


def _rooms(**_):
    client, error = _client()
    if error:
        return error
    try:
        return _answer(client.get_rooms(), ('rooms',), "Listing the rooms")
    except Exception as e:
        return f"Could not list the rooms: {e}"


def _online(**_):
    client, error = _client()
    if error:
        return error
    try:
        return _answer(client.get_online_users(), ('users', 'online_users'),
                       "Listing who is online")
    except Exception as e:
        return f"Could not list who is online: {e}"


def _people(**_):
    client, error = _client()
    if error:
        return error
    try:
        return _answer(client.get_all_users(), ('users',), "Listing the users")
    except Exception as e:
        return f"Could not list the users: {e}"


def _room_messages(room='', limit=50, **_):
    client, error = _client()
    if error:
        return error
    room_id, problem = _resolve_room(client, room)
    if problem:
        return problem
    try:
        return _answer(client.get_room_messages(room_id, limit=int(limit or 50)),
                       ('messages',), "Reading the room")
    except Exception as e:
        return f"Could not read the room: {e}"


def _conversation(username='', limit=50, **_):
    client, error = _client()
    if error:
        return error
    who = str(username or '').strip()
    if not who:
        return "Say whose conversation to read."
    try:
        from src.ai.titan_tools import _titan_net_resolve_recipient
        user_id, problem = _titan_net_resolve_recipient(client, who)
        if not user_id:
            return problem or f"There is no Titan-Net user '{who}'."
        return _answer(client.get_private_messages(user_id, limit=int(limit or 50)),
                       ('messages',), f"Reading the conversation with {who}")
    except Exception as e:
        return f"Could not read the conversation: {e}"


def _topics(category='', limit=50, **_):
    client, error = _client()
    if error:
        return error
    try:
        result = client.get_forum_topics(category=(category or None),
                                         limit=int(limit or 50))
        return _answer(result, ('topics',), "Listing the topics")
    except Exception as e:
        return f"Could not list the topics: {e}"


def _topic(topic='', limit=100, **_):
    """One topic and its replies, in one answer - a window shows both."""
    client, error = _client()
    if error:
        return error
    text = str(topic or '').strip()
    if not text.isdigit():
        return "Say the topic's number."
    topic_id = int(text)
    try:
        head = client.get_forum_topic(topic_id)
        if not isinstance(head, dict) or not head.get('success'):
            return _answer(head, ('topic',), "Reading the topic")
        replies = client.get_forum_replies(topic_id, limit=int(limit or 100))
    except Exception as e:
        return f"Could not read the topic: {e}"
    payload = _payload(head, ('topic',))
    if isinstance(replies, dict) and replies.get('success'):
        payload['replies'] = replies.get('replies') or []
    return json.dumps(payload, ensure_ascii=False, default=str)


def _groups(**_):
    client, error = _client()
    if error:
        return error
    try:
        return _answer(client.list_groups(), ('groups',), "Listing the groups")
    except Exception as e:
        return f"Could not list the groups: {e}"


def _mailbox(folder='inbox', **_):
    client, error = _client()
    if error:
        return error
    try:
        return _answer(client.get_mailbox(folder=str(folder or 'inbox')),
                       ('mail', 'messages'), "Reading the mailbox")
    except Exception as e:
        return f"Could not read the mailbox: {e}"


def _mail(mail='', **_):
    client, error = _client()
    if error:
        return error
    text = str(mail or '').strip()
    if not text.isdigit():
        return "Say the message's number."
    try:
        return _answer(client.get_mail(int(text)), ('mail', 'message'),
                       "Reading the message")
    except Exception as e:
        return f"Could not read the message: {e}"


def _whoami(**_):
    """Who Titan is signed in to Titan-Net as - what a client puts in its
    title, and the one thing it must not get wrong."""
    client, error = _client()
    if error:
        return error
    return json.dumps({'username': getattr(client, 'username', '') or '',
                       'user_id': getattr(client, 'user_id', None)},
                      ensure_ascii=False, default=str)



def _news(**_):
    """What is new on Titan-Net, as counts rather than as a sentence.

    `whats_new` already answers this in prose, which is right for reading
    aloud once. A client that wants to NOTICE something new needs the
    numbers: unread messages, unread forum topics, new applications and
    updates, so it can compare them with what it saw last time.
    """
    client, error = _client()
    if error:
        return error
    try:
        result = client.get_whats_new()
    except Exception as e:
        return f"Could not read what is new: {e}"
    if not isinstance(result, dict) or not result.get('success'):
        detail = ''
        if isinstance(result, dict):
            detail = str(result.get('error') or '')
        return "Reading what is new did not work." + (f" {detail}" if detail else '')
    wanted = ('unread_messages', 'unread_forum_topics', 'new_apps',
              'app_updates', 'unread_mail')
    counts = {key: result[key] for key in wanted if key in result}
    return json.dumps(counts, ensure_ascii=False, default=str)


def get_titannet_data_actions():
    """(name, summary, params, risk, run) for each, as the shell's are."""
    string = {'type': 'string'}
    number = {'type': 'number'}
    return (
        ('whoami', "Who Titan is signed in to Titan-Net as, as JSON.", {},
         'auto', _whoami),
        ('news', "What is new on Titan-Net as counts, for a client that "
                  "wants to notice something arriving.", {}, 'auto', _news),
        ('rooms', "The chat rooms as JSON: id, name, type, whether it has a "
                  "password.", {}, 'auto', _rooms),
        ('online', "Who is online, as JSON.", {}, 'auto', _online),
        ('people', "Every registered user, as JSON.", {}, 'auto', _people),
        ('room_messages', "Recent messages in one room, as JSON.",
         {'room': dict(string, description="The room's name or its number.",
                       required=True),
          'limit': dict(number, description="How many (default 50).")},
         'auto', _room_messages),
        ('conversation', "The private conversation with one person, as JSON.",
         {'username': dict(string, description="Their username.",
                           required=True),
          'limit': dict(number, description="How many (default 50).")},
         'auto', _conversation),
        ('topics', "Forum topics as JSON.",
         {'category': dict(string, description="One category only."),
          'limit': dict(number, description="How many (default 50).")},
         'auto', _topics),
        ('topic', "One forum topic AND its replies, as JSON.",
         {'topic': dict(string, description="The topic's number.",
                        required=True),
          'limit': dict(number, description="How many replies (default 100).")},
         'auto', _topic),
        ('groups', "The groups as JSON.", {}, 'auto', _groups),
        ('mailbox', "A Titan Mail folder as JSON.",
         {'folder': dict(string, description="inbox, sent or unread "
                         "(default inbox).")},
         'auto', _mailbox),
        ('mail', "One mail message as JSON.",
         {'mail': dict(string, description="The message's number.",
                       required=True)},
         'auto', _mail),
    )


# --------------------------------------------------------------------------- #
# The rest of what Titan-Net's own window can do
#
# `titannet_tools.py` covers reading and writing messages; these are the
# things one does to the PLACE rather than in it - making a room, leaving
# one, blocking somebody, the account's own address, the groups. They are
# here rather than there because they are not things to say in a sentence to
# a model: they are what a client's menus are made of.
#
# Voice and push-to-talk are deliberately absent. They are a live audio
# stream captured and played in Titan's own process; an action that started
# one from another program would take the microphone with nobody in front of
# it, and the sound would come out where Titan is, not where the caller is.
# --------------------------------------------------------------------------- #
def _room_id(client, room):
    return _resolve_room(client, room)


def _user_id(client, username):
    from src.ai.titan_tools import _titan_net_resolve_recipient
    return _titan_net_resolve_recipient(client, str(username or '').strip())


def _did(result, what):
    if isinstance(result, dict) and result.get('success'):
        return f"{what} - done."
    detail = ''
    if isinstance(result, dict):
        detail = str(result.get('error') or result.get('message') or '')
    return f"{what} did not work." + (f" {detail}" if detail else '')


def _create_room(name='', description='', kind='text', password='', **_):
    client, error = _client()
    if error:
        return error
    if not str(name or '').strip():
        return "Give the room a name."
    try:
        return _did(client.create_room(str(name), str(description or ''),
                                       str(kind or 'text'), str(password or '')),
                    f"Creating the room {name}")
    except Exception as e:
        return f"Could not create the room: {e}"


def _join_room(room='', password='', **_):
    client, error = _client()
    if error:
        return error
    room_id, problem = _room_id(client, room)
    if problem:
        return problem
    try:
        return _did(client.join_room(room_id, str(password or '')),
                    f"Joining {room}")
    except Exception as e:
        return f"Could not join: {e}"


def _leave_room(room='', **_):
    client, error = _client()
    if error:
        return error
    room_id, problem = _room_id(client, room)
    if problem:
        return problem
    try:
        return _did(client.leave_room(room_id), f"Leaving {room}")
    except Exception as e:
        return f"Could not leave: {e}"


def _delete_room(room='', **_):
    client, error = _client()
    if error:
        return error
    room_id, problem = _room_id(client, room)
    if problem:
        return problem
    try:
        return _did(client.delete_room(room_id), f"Deleting {room}")
    except Exception as e:
        return f"Could not delete it: {e}"


def _block(username='', **_):
    client, error = _client()
    if error:
        return error
    user_id, problem = _user_id(client, username)
    if not user_id:
        return problem or f"There is no Titan-Net user '{username}'."
    try:
        return _did(client.block_user(user_id), f"Blocking {username}")
    except Exception as e:
        return f"Could not block them: {e}"


def _unblock(username='', **_):
    client, error = _client()
    if error:
        return error
    user_id, problem = _user_id(client, username)
    if not user_id:
        return problem or f"There is no Titan-Net user '{username}'."
    try:
        return _did(client.unblock_user(user_id), f"Unblocking {username}")
    except Exception as e:
        return f"Could not unblock them: {e}"


def _blocked(**_):
    client, error = _client()
    if error:
        return error
    try:
        return _answer(client.get_blocked_users(), ('users', 'blocked_users'),
                       "Listing who is blocked")
    except Exception as e:
        return f"Could not list them: {e}"


def _account_email(email='', **_):
    """Read the account's recovery address, or set it."""
    client, error = _client()
    if error:
        return error
    try:
        if str(email or '').strip():
            return _did(client.set_account_email(str(email).strip()),
                        "Setting the address")
        return _answer(client.get_account_email(), ('email', 'address'),
                       "Reading the address")
    except Exception as e:
        return f"Could not do that: {e}"


def _create_group(name='', description='', **_):
    client, error = _client()
    if error:
        return error
    if not str(name or '').strip():
        return "Give the group a name."
    try:
        return _did(client.create_group(str(name), str(description or '') or None),
                    f"Creating the group {name}")
    except Exception as e:
        return f"Could not create it: {e}"


def _join_group(group='', **_):
    client, error = _client()
    if error:
        return error
    text = str(group or '').strip()
    if not text.isdigit():
        return "Say the group's number."
    try:
        return _did(client.join_group(int(text)), f"Joining group {text}")
    except Exception as e:
        return f"Could not join it: {e}"


def _broadcast(message='', **_):
    """Send a message to everybody - what Titan-Net calls a broadcast."""
    client, error = _client()
    if error:
        return error
    if not str(message or '').strip():
        return "Say what to broadcast."
    try:
        return _did(client.send_broadcast(str(message)), "Broadcasting")
    except Exception as e:
        return f"Could not broadcast: {e}"


def get_titannet_place_actions():
    """(name, summary, params, risk, run) for each, as the shell's are."""
    string = {'type': 'string'}
    return (
        ('create_room', "Make a new Titan-Net chat room.",
         {'name': dict(string, description="What to call it.", required=True),
          'description': dict(string, description="What it is for."),
          'kind': dict(string, description="text or voice (default text)."),
          'password': dict(string, description="A password, if it needs one.")},
         'confirm', _create_room),
        ('join_room', "Join a Titan-Net room.",
         {'room': dict(string, description="Its name or number.",
                       required=True),
          'password': dict(string, description="Its password, if it has one.")},
         'confirm', _join_room),
        ('leave_room', "Leave a Titan-Net room.",
         {'room': dict(string, description="Its name or number.",
                       required=True)},
         'confirm', _leave_room),
        ('delete_room', "Delete a Titan-Net room you own.",
         {'room': dict(string, description="Its name or number.",
                       required=True)},
         'always_confirm', _delete_room),
        ('block', "Block a Titan-Net user.",
         {'username': dict(string, description="Their username.",
                           required=True)},
         'always_confirm', _block),
        ('unblock', "Unblock a Titan-Net user.",
         {'username': dict(string, description="Their username.",
                           required=True)},
         'confirm', _unblock),
        ('blocked', "Who you have blocked, as JSON.", {}, 'auto', _blocked),
        ('account_email',
         "The account's recovery address; give one to set it.",
         {'email': dict(string, description="The new address (optional).")},
         'confirm', _account_email),
        ('create_group', "Make a Titan-Net group.",
         {'name': dict(string, description="What to call it.", required=True),
          'description': dict(string, description="What it is for.")},
         'confirm', _create_group),
        ('join_group_by_id', "Join a Titan-Net group by its number.",
         {'group': dict(string, description="The group's number.",
                        required=True)},
         'confirm', _join_group),
        ('broadcast', "Send a message to everybody on Titan-Net.",
         {'message': dict(string, description="What to say.", required=True)},
         'always_confirm', _broadcast),
    )


# --------------------------------------------------------------------------- #
# The rest of Titan-Net's window: the Feedback Hub, the application
# repository and the announcements. Records, for a client to draw.
# --------------------------------------------------------------------------- #
def _feedback(kind='', **_):
    client, error = _client()
    if error:
        return error
    try:
        return _answer(client.list_feedback(str(kind or '') or None),
                       ('items', 'feedback'), "Listing the feedback")
    except Exception as e:
        return f"Could not list it: {e}"


def _feedback_item(item='', **_):
    client, error = _client()
    if error:
        return error
    text = str(item or '').strip()
    if not text.isdigit():
        return "Say the item's number."
    try:
        return _answer(client.get_feedback(int(text)), ('item', 'feedback'),
                       "Reading the item")
    except Exception as e:
        return f"Could not read it: {e}"


def _feedback_new(kind='feedback', title='', content='', **_):
    client, error = _client()
    if error:
        return error
    if not str(title or '').strip() or not str(content or '').strip():
        return "A title and something to say are both needed."
    try:
        return _did(client.create_feedback(str(kind or 'feedback'), str(title),
                                           str(content)), "Sending it")
    except Exception as e:
        return f"Could not send it: {e}"


def _feedback_upvote(item='', **_):
    client, error = _client()
    if error:
        return error
    text = str(item or '').strip()
    if not text.isdigit():
        return "Say the item's number."
    try:
        return _did(client.upvote_feedback(int(text)), "Voting for it")
    except Exception as e:
        return f"Could not vote: {e}"


def _repository(category='', query='', **_):
    client, error = _client()
    if error:
        return error
    try:
        if str(query or '').strip():
            result = client.search_apps(str(query), str(category or '') or None)
        else:
            result = client.get_apps(None, str(category or '') or None)
        return _answer(result, ('apps', 'packages'), "Reading the repository")
    except Exception as e:
        return f"Could not read the repository: {e}"


def _repository_item(app='', **_):
    client, error = _client()
    if error:
        return error
    text = str(app or '').strip()
    if not text.isdigit():
        return "Say the package's number."
    try:
        return _answer(client.get_app_details(int(text)), ('app', 'package'),
                       "Reading the package")
    except Exception as e:
        return f"Could not read it: {e}"


def _repository_download(app='', **_):
    """Download a package. It lands where Titan puts downloads, because
    Titan is where it will be installed."""
    client, error = _client()
    if error:
        return error
    text = str(app or '').strip()
    if not text.isdigit():
        return "Say the package's number."
    try:
        result = client.download_app(int(text))
    except Exception as e:
        return f"Could not download it: {e}"
    if isinstance(result, dict) and result.get('success'):
        where = result.get('path') or result.get('file') or ''
        return f"Downloaded." + (f" It is at {where}." if where else '')
    return _did(result, "Downloading it")


def _announcements(**_):
    client, error = _client()
    if error:
        return error
    try:
        return _answer(client.list_broadcast_files(), ('files', 'broadcasts'),
                       "Listing the announcements")
    except Exception as e:
        return f"Could not list them: {e}"


def _announcement(name='', **_):
    client, error = _client()
    if error:
        return error
    if not str(name or '').strip():
        return "Say which announcement."
    try:
        return _answer(client.get_broadcast_file(str(name)),
                       ('content', 'text', 'file'), "Reading the announcement")
    except Exception as e:
        return f"Could not read it: {e}"


def get_titannet_hub_actions():
    """(name, summary, params, risk, run) for each, as the shell's are."""
    string = {'type': 'string'}
    return (
        ('feedback', "The Feedback Hub as JSON.",
         {'kind': dict(string, description="feedback, bug or idea "
                       "(default all).")},
         'auto', _feedback),
        ('feedback_item', "One Feedback Hub item as JSON.",
         {'item': dict(string, description="Its number.", required=True)},
         'auto', _feedback_item),
        ('feedback_new', "Send something to the Feedback Hub.",
         {'kind': dict(string, description="feedback, bug or idea."),
          'title': dict(string, description="Its title.", required=True),
          'content': dict(string, description="What to say.", required=True)},
         'confirm', _feedback_new),
        ('feedback_upvote', "Vote for a Feedback Hub item.",
         {'item': dict(string, description="Its number.", required=True)},
         'confirm', _feedback_upvote),
        ('repository', "The application repository as JSON.",
         {'category': dict(string, description="One category only."),
          'query': dict(string, description="Search for this instead.")},
         'auto', _repository),
        ('repository_item', "One package in the repository, as JSON.",
         {'app': dict(string, description="Its number.", required=True)},
         'auto', _repository_item),
        ('repository_download', "Download a package from the repository.",
         {'app': dict(string, description="Its number.", required=True)},
         'confirm', _repository_download),
        ('announcements', "The announcements as JSON.", {}, 'auto',
         _announcements),
        ('announcement', "One announcement, as JSON.",
         {'name': dict(string, description="Its file name.", required=True)},
         'auto', _announcement),
    )
