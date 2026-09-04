# -*- coding: utf-8 -*-
"""`EltenLink.*` - answered by the EltenLink client Titan already has.

Copyright (C) 2026 titosoft. Part of the Elten API bridge, licensed under the
GNU General Public License version 3 or later; see `LICENSE` beside this
component.

An Elten application that reaches for the network is asking EltenLink, and
Titan is already signed in to EltenLink: `src/eltenlink_client/` is a full
client (login and 2FA, messages, contacts, forums, blogs, profiles) and Titan
IM keeps the user's credentials. So this does not stub the server - it uses
that client, with the session the user already has.

Three rules make it safe to hand somebody else's code:

* **The application never sees a credential.** It cannot ask for the token,
  the password or the session; it asks for "the forum groups" and gets them.
  Nothing here takes a username and password from the application either -
  the account is the one the user signed in to Titan with, and an
  application cannot sign in as somebody else.
* **The table is explicit** (`CALLS`). An application can reach
  `EltenLink::Forum.groups` because it is written down here; it cannot reach
  an attribute of the client object, and it cannot reach a method nobody
  listed - `getattr` is never called on a name the application supplied.
* **Nothing writes without the user having asked.** Everything that PUBLISHES
  - a post, a reply, a message, a blog entry - is deliberately absent from
  the table. An application that wants to post has to go through the same
  place a person would, and an `.eltenapp` from a repository cannot post to
  somebody's forum in their name because it was opened.

What is not in the table raises `EltenLink::Error` on the Ruby side, which is
the error applications are already written to rescue (24 call sites across
the installed ones) - so an application asking for something Titan cannot do
degrades the way it would against a server that refused it, rather than
dying on `NoMethodError`.
"""

import threading

_client = None
_lock = threading.Lock()


class EltenUnavailable(Exception):
    """No session, with a sentence saying why."""


def client():
    """Titan's own EltenLink client, signed in, or raise.

    Built once and kept: signing in is a round trip and an application that
    asks five questions must not make five sessions.
    """
    global _client
    with _lock:
        if _client is not None:
            return _client
        try:
            from src.eltenlink_client.elten_client import EltenClient
        except Exception as error:
            raise EltenUnavailable('Titan has no EltenLink client: %s' % error)
        try:
            from src.settings.titan_im_config import get_eltenlink_credentials
            username, token, password = get_eltenlink_credentials()
        except Exception as error:
            raise EltenUnavailable('the EltenLink account could not be read: %s'
                                   % error)
        if not username:
            raise EltenUnavailable(
                'nobody is signed in to EltenLink. Sign in through Titan IM '
                'and this application can use the network.')
        found = EltenClient()
        # The token the user already has, first; the saved password only if
        # that token has expired. Neither is ever shown to the application.
        signed_in = False
        if token:
            try:
                found.token = token
                found.username = username
                signed_in = bool(found.check_token())
            except Exception:
                signed_in = False
        if not signed_in and password:
            try:
                answer = found.login(username, password)
                signed_in = bool(answer and answer.get('success', answer))
            except Exception as error:
                raise EltenUnavailable('EltenLink refused the sign-in: %s'
                                       % error)
        if not signed_in:
            raise EltenUnavailable(
                'the EltenLink session has expired. Sign in again through '
                'Titan IM.')
        _client = found
        return _client


def whoami():
    """The name the user is signed in to EltenLink as, or ''.

    Deliberately NOT a login: `Session.name` is read by applications
    constantly - the Game Room asks it thirty times to know whose table
    it is looking at - and the name is already saved beside the account,
    so this answers it without reaching the network and without needing a
    live session at all. The token is never part of the answer.
    """
    try:
        from src.settings.titan_im_config import get_eltenlink_credentials
        username, _token, _password = get_eltenlink_credentials()
        return str(username or '')
    except Exception:
        return ''


def forget():
    """Drop the session - the user signed out, or Titan is closing."""
    global _client
    with _lock:
        _client = None


#: `namespace.method` -> what to call on Titan's client.
#:
#: Deliberately a table and not `getattr`: an application names a key in
#: here or it reaches nothing at all. Everything listed only READS - see the
#: note at the top of the file about why nothing that publishes is here.
CALLS = {
    # Who is who
    'Users.online': 'get_online_users',
    'Users.info': 'get_profile',
    'Users.exists': 'user_exists',
    'Users.search': 'search_users',
    'Users.status_info': 'get_user_status',
    'Profiles.get': 'get_profile',

    # Messages
    'Messages.conversations': 'get_conversations',
    'Messages.subjects': 'get_conversation_subjects',
    'Messages.list': 'get_conversation_messages',
    'Messages.users': 'get_conversations',
    'Messages.unread': 'get_new_messages',

    # People
    'Contacts.list': 'get_contacts',

    # The forum
    'Forum.structure': 'get_forum_structure',
    'Forum.groups': 'get_forum_groups',
    'Forum.forums': 'get_forums_in_group',
    'Forum.threads': 'get_threads_in_forum',
    'Forum.posts': 'get_thread_posts',
    'Forum.search': 'search_forum',
    'Forum.members': 'get_group_members',

    # Blogs
    'Blog.list': 'get_blogs_list',
    'Blog.posts': 'get_blog_posts',
    'Blog.categories': 'get_blog_categories',
    'Blog.post': 'get_blog_post_content',
    'Blog.exists': 'check_blog_exists',

    # The account, as far as an application may see it
    'System.account': 'get_account_info',
}


def call(namespace, method, arguments):
    """One `EltenLink::<Namespace>.<method>` call, or raise.

    `arguments` is whatever the application passed, positionally. It is
    handed to the client as-is: these are strings and numbers off the wire,
    and the client validates its own inputs.
    """
    key = '%s.%s' % (namespace, method)
    name = CALLS.get(key)
    if name is None:
        raise EltenUnavailable(
            'Titan does not implement EltenLink.%s' % key)
    found = client()
    handler = getattr(found, name, None)
    if handler is None:
        raise EltenUnavailable(
            'this Titan\'s EltenLink client has no %s' % name)
    return handler(*arguments)
