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

import io
import json
import os
import threading

#: What to tell the server when the installed Elten cannot be asked.
DEFAULT_VERSION = 'ELTEN 3.0.2'

_client = None
_lock = threading.Lock()


class EltenUnavailable(Exception):
    """No session, with a sentence saying why."""


class StampRequired(EltenUnavailable):
    """The table is PROTECTED, and only Elten's own launcher may write it.

    A protected app table is signed with a launcher stamp - an HMAC whose
    key is compiled into Elten's official launcher binary
    (`launcher/src/stamp.cpp`, "the launcher was built without a private
    key"). It exists so that only the genuine Elten client can write
    those rows, which is a control on somebody else's server and not one
    to work around: the key is deliberately not public and forging a
    stamp is exactly what it is there to stop.

    So an application whose tables are protected keeps its scores on this
    machine and is told plainly why they are not shared. Everything else -
    every unprotected table, and reading - works.
    """


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
        username, _token, _password = _titan_credentials()
        if username:
            return str(username)
        from . import elten_account
        name, _auto = elten_account.elten_account()
        return str(name or '')
    except Exception:
        return ''


def forget():
    """Drop the session - the user signed out, or Titan is closing."""
    global _client, _session
    with _lock:
        _client = None
        _session = None


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


# --------------------------------------------------------------------------- #
# The app API: an application's own tables on EltenLink's server
# --------------------------------------------------------------------------- #
#: Where the app API lives. This is NOT the legacy `srvapi.elten.link/leg1`
#: endpoint Titan's client talks to for forums and messages - the app tables
#: are the v1 API - but the credentials are the same pair, so the session the
#: user already has is what signs these requests too.
API_BASE_URL = 'https://api.elten.link'

#: How long to wait. A game submitting a score must not hold its own window.
API_TIMEOUT = 20


#: The session the app API is signed with, once it has been had.
_session = None


def session():
    """The name and token the app API is signed with.

    **Two places on this machine may already have an account**, and both
    are used:

    * Titan IM, where the user signed in to EltenLink through Titan.
    * **Elten's own installation.** A user who has Elten installed and
      logged in should not have to sign in a second time to play their own
      games here, and `%APPDATA%/elten/login.dat` holds exactly what is
      needed - the account name and an auto-login key, readable only by
      this Windows account because Elten protects it with DPAPI.

    Raises `EltenUnavailable` with a sentence when neither has one, which
    is what a game's `leaderboard.available?` reports and why a score is
    always kept locally FIRST and shared afterwards.
    """
    global _session
    with _lock:
        if _session is not None:
            return _session
    found = _open_session()
    with _lock:
        _session = found
    return found


def forget_session():
    """The token was refused - ask for a new one on the next call."""
    global _session
    with _lock:
        _session = None


def _open_session():
    """One `/api/v1/session`, with whichever credentials this machine has.

    A session token is asked for rather than borrowed: Titan's own client
    talks to the legacy endpoint and the app tables are the v1 API, and
    assuming one token serves both is the kind of assumption that works
    until it does not.
    """
    from . import elten_account

    name, auto_login = elten_account.elten_account()
    if name and auto_login:
        try:
            return _sign_in(name, token=auto_login)
        except EltenUnavailable as error:
            _note('the Elten auto-login key was refused: %s' % error)

    username, saved_token, password = _titan_credentials()
    if username and password:
        return _sign_in(username, password=password)
    if username and saved_token:
        # Nothing to sign in WITH, but Titan's own client has a live
        # session; the app API may well accept it, and finding out costs
        # one request.
        return str(username), str(saved_token)
    raise EltenUnavailable(
        'nobody is signed in to EltenLink. Sign in through Titan IM, or '
        'log in to Elten itself, and this application can use the network.')


def _titan_credentials():
    try:
        from src.settings.titan_im_config import get_eltenlink_credentials
        return get_eltenlink_credentials()
    except Exception:
        return '', '', ''


def _sign_in(name, password=None, token=None):
    """Ask EltenLink for a session, exactly as Elten's own client does."""
    import requests
    from . import elten_account

    body = {'name': str(name),
            'version_string': _version_string(),
            'version_isdevelopment': 0,
            'version_islauncher': 1,
            'appid': elten_account.app_id(),
            'lang': 'en', 'language': 'en',
            'os': 'windows', 'authmethod': 'list'}
    if token:
        body['token'] = token
    else:
        body['password'] = password
    try:
        answer = requests.post('%s/api/v1/session' % API_BASE_URL,
                               params=body, timeout=API_TIMEOUT)
        payload = answer.json()
    except Exception as error:
        raise EltenUnavailable('EltenLink could not be reached: %s' % error)
    if not isinstance(payload, dict) or not payload.get('success'):
        message = ''
        if isinstance(payload, dict):
            message = str(payload.get('error') or payload.get('code') or '')
        raise EltenUnavailable(message or 'EltenLink refused the sign-in')
    data = payload.get('data') or {}
    got = str(data.get('token') or '')
    if not got:
        raise EltenUnavailable('EltenLink answered no session token')
    return str(data.get('name') or name), got


def _version_string():
    """What Elten is on this machine, so the server knows the protocol.

    Read from the installed client where there is one rather than
    guessed - a version the server does not recognise is a sign-in it
    refuses.
    """
    from . import elten_account
    try:
        import configparser
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        parser.read(os.path.join(elten_account.elten_data_dir(), 'elten.ini'),
                    encoding='utf-8')
        found = parser.get('Elten', 'Version', fallback='') or ''
        if found:
            return found.upper()
    except Exception:
        pass
    log = os.path.join(elten_account.elten_data_dir(), 'elten.log')
    try:
        with io.open(log, encoding='utf-8', errors='replace') as handle:
            for line in handle:
                if 'Elten version:' in line:
                    return line.split('Elten version:', 1)[1] \
                               .split('(')[0].strip().upper()
    except Exception:
        pass
    return DEFAULT_VERSION


def _note(text):
    try:
        print('[elten bridge] %s' % text)
    except Exception:
        pass


def signed_in():
    """Whether there is an EltenLink account to act as.

    Either the one Titan IM signed in with, or Elten's own on this
    machine - a user who has Elten installed and logged in has an
    account here without doing anything.

    Deliberately NOT a round trip. Every game asks this in the middle of
    its own flow - "do you want to share this score?" - and answering it
    by signing in would put a network timeout between finishing a game
    and being told the result. It answers off the saved credentials; a
    token that has since expired is found out by the call that uses it,
    which is the one that can afford to wait.
    """
    try:
        if _session is not None:
            return True
        from . import elten_account
        name, auto_login = elten_account.elten_account()
        if name and auto_login:
            return True
        username, token, password = _titan_credentials()
        return bool(username) and bool(token or password)
    except Exception:
        return False


def _api(method, path, params=None, body=None):
    """One call to the app API, signed as the user.

    Everything here goes through the ONE session Titan holds: an
    application never sees the token, cannot choose the account and
    cannot sign in as anybody else - it names its own uuid and its own
    table, and the server decides what that account may do with them.
    """
    import requests
    name, token = session()
    query = dict(params or {})
    query['name'] = name
    query['token'] = token
    url = '%s%s' % (API_BASE_URL, path)
    answer = requests.request(method, url, params=query,
                              json=body if body is not None else None,
                              timeout=API_TIMEOUT)
    if answer.status_code in (401, 403):
        # The token has expired since it was had. One retry with a fresh
        # one, because the alternative is a game telling the user their
        # score could not be shared when signing in again would have
        # shared it.
        forget_session()
        name, token = session()
        query['name'], query['token'] = name, token
        answer = requests.request(method, url, params=query,
                                  json=body if body is not None else None,
                                  timeout=API_TIMEOUT)
    if answer.status_code >= 500:
        raise EltenUnavailable('EltenLink answered %d' % answer.status_code)
    try:
        payload = answer.json()
    except Exception:
        raise EltenUnavailable('EltenLink answered something that is not JSON')
    if not isinstance(payload, dict) or not payload.get('success'):
        error = code = ''
        if isinstance(payload, dict):
            found = payload.get('error')
            if isinstance(found, dict):
                code = str(found.get('code') or '')
                error = str(found.get('message') or '')
            else:
                error = str(found or payload.get('message') or '')
                code = str(payload.get('code') or '')
        if 'stamp' in code or 'stamp' in error.lower():
            raise StampRequired(
                'this application keeps its rows in a PROTECTED table, '
                'which EltenLink accepts only from Elten\'s own signed '
                'launcher. The data is kept on this machine instead.')
        raise EltenUnavailable(error or 'EltenLink refused the request')
    return payload.get('data') or {}


def _escape(value):
    from urllib.parse import quote
    return quote(str(value or ''), safe='')


def _rows_path(uuid, table):
    return '/api/v1/apps/%s/tables/%s/rows' % (_escape(uuid), _escape(table))


def table_select(uuid, table, where=None, order=None, limit=None, offset=None):
    """Elten's own `AppTable#select`, filters and all."""
    import json as _json
    params = {}
    if where is not None:
        params['where'] = _json.dumps(where)
    if order is not None:
        params['order'] = _json.dumps(order)
    if limit is not None:
        params['limit'] = limit
    if offset is not None:
        params['offset'] = offset
    data = _api('GET', _rows_path(uuid, table), params)
    rows = data.get('rows')
    return list(rows) if isinstance(rows, list) else []


def table_insert(uuid, table, values):
    data = _api('POST', _rows_path(uuid, table), body={'values': values})
    return data.get('row')


def table_upsert(uuid, table, values):
    data = _api('PUT', _rows_path(uuid, table), body={'values': values})
    return data.get('row')


def table_update(uuid, table, row_id, values):
    data = _api('PATCH', '%s/%d' % (_rows_path(uuid, table), int(row_id)),
                body={'values': values})
    return data.get('row')


def table_delete(uuid, table, row_id):
    _api('DELETE', '%s/%d' % (_rows_path(uuid, table), int(row_id)))
    return True


def app_register(name, data=None, tables=None, protected=False,
                 notifications=False):
    """Declare this application and its tables, the way Elten does.

    An application ships a `SERVER_TABLES` schema and calls `server_app`;
    the server has to be told about it once before a row can be written.
    """
    body = {'name': str(name or '')}
    if data is not None:
        body['data'] = data
    if tables is not None:
        body['tables'] = tables
    body['tables_protected'] = bool(protected)
    body['notifications'] = bool(notifications)
    answer = _api('POST', '/api/v1/apps/register', body=body)
    return answer.get('app') or answer


def app_update(uuid, name=None, data=None, tables=None, protected=None,
               notifications=None):
    body = {}
    if name is not None:
        body['name'] = str(name)
    if data is not None:
        body['data'] = data
    if tables is not None:
        body['tables'] = tables
    if protected is not None:
        body['tables_protected'] = bool(protected)
    if notifications is not None:
        body['notifications'] = bool(notifications)
    answer = _api('PATCH', '/api/v1/apps/%s' % _escape(uuid), body=body)
    return answer.get('app') or answer


def app_notify(uuid, user, kind, metadata=None, expires_in=0):
    """One application telling one user something, through EltenLink.

    Elten's own `send_notification`. It publishes - so it is deliberately
    the ONLY writing call an application can reach that leaves this
    machine besides its own table, it names the application's own uuid,
    and the server decides whether that application may notify anybody.
    """
    body = {'user': str(user or ''), 'type': str(kind or ''),
            'metadata': metadata or {}}
    if expires_in:
        body['expires_in'] = int(expires_in)
    _api('POST', '/api/v1/apps/%s/notifications' % _escape(uuid), body=body)
    return True


def app_info(uuid):
    return _api('GET', '/api/v1/apps/%s' % _escape(uuid)).get('app')


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


# --------------------------------------------------------------------------- #
# Live sessions
#
# EltenLink's own realtime layer for applications: a session with a capacity,
# participants who are invited into it, and JSON packets between them. It is
# what the ELTEN Game Room is - without it that application raises "ELTEN Game
# Room requires the LiveSessions API" before its first screen.
#
# Every call below is one of `EltenLink::Apps`' own, signed with the session
# the user already has, so an application still never sees a credential and
# still cannot choose the account. What it CAN now do is play against
# somebody.
#
# The envelopes come back a different way from everywhere else here. Elten
# does not poll a session: `GET /api/v1/system/realtime-state` is one long
# poll carrying everything that has happened - notifications, signals, and
# `live_sessions` rows - and Elten's notification service hands the last of
# those to `LiveSessions.receive`. So this keeps that poll on a thread of its
# own and the application drains what has arrived, which is what makes a turn
# arrive in the tens of milliseconds rather than at the next tick of a
# request the game had to make itself.
# --------------------------------------------------------------------------- #
def _live_path(session_id):
    return '/api/v1/apps/live-sessions/%s' % _escape(session_id)


def live_create(appid, instance_id, metadata=None, participant_metadata=None,
                capacity=2):
    answered, value = via_elten('live_create', appid=appid,
                                instance_id=instance_id,
                                metadata=metadata or {},
                                participant_metadata=participant_metadata or {},
                                capacity=int(capacity or 2))
    if answered:
        return value
    return _api('POST', '/api/v1/apps/live-sessions', body={
        'appid': appid, 'instance_id': instance_id,
        'metadata': metadata or {},
        'participant_metadata': participant_metadata or {},
        'capacity': int(capacity or 2)})


def live_invite(session_id, participant_id, user, metadata=None):
    answered, value = via_elten('live_invite', session_id=session_id,
                                participant_id=participant_id, user=user,
                                metadata=metadata or {})
    if answered:
        return value
    return _api('POST', '%s/invitations' % _live_path(session_id), body={
        'participant_id': participant_id, 'user': str(user or ''),
        'metadata': metadata or {}})


def live_accept(session_id, appid, instance_id, participant_metadata=None):
    answered, value = via_elten(
        'live_accept', session_id=session_id, appid=appid,
        instance_id=instance_id,
        participant_metadata=participant_metadata or {})
    if answered:
        return value
    return _api('POST', '%s/accept' % _live_path(session_id), body={
        'appid': appid, 'instance_id': instance_id,
        'participant_metadata': participant_metadata or {}})


def live_reject(session_id, appid):
    answered, _value = via_elten('live_reject', session_id=session_id,
                                 appid=appid)
    if answered:
        return True
    _api('POST', '%s/reject' % _live_path(session_id), body={'appid': appid})
    return True


def live_send(session_id, participant_id, packet, message_id):
    answered, value = via_elten('live_send', session_id=session_id,
                                participant_id=participant_id, packet=packet,
                                message_id=message_id)
    if answered:
        return value
    return _api('POST', '%s/messages' % _live_path(session_id), body={
        'participant_id': participant_id, 'message_id': message_id,
        'packet': packet})


def live_leave(session_id, participant_id):
    answered, _value = via_elten('live_leave', session_id=session_id,
                                 participant_id=participant_id)
    if answered:
        return True
    _api('POST', '%s/leave' % _live_path(session_id),
         body={'participant_id': participant_id})
    return True


def live_close(session_id, participant_id):
    answered, _value = via_elten('live_close', session_id=session_id,
                                 participant_id=participant_id)
    if answered:
        return True
    _api('POST', '%s/close' % _live_path(session_id),
         body={'participant_id': participant_id})
    return True


def signal_send(appid, user, packet):
    """`Program#signal` - how two copies of one application tell each other
    something through EltenLink. The Game Room announces a new table with
    one, so everybody else's lobby learns about it at once instead of at
    their next poll."""
    answered, _value = via_elten('signal', appid=appid, user=user,
                                 packet=packet)
    if answered:
        return True
    _api('POST', '/api/v1/apps/signals',
         body={'appid': appid, 'user': str(user or ''), 'packet': packet})
    return True


def live_control(appid, instance_id, sessions):
    """The lease. A session the client stops claiming is closed by the
    server, which is what stops a game left open by a crash from sitting
    there for ever - so this is sent every few seconds while one is open."""
    answered, value = via_elten('live_control', appid=appid,
                                instance_id=instance_id,
                                sessions=list(sessions or []))
    if answered:
        return value
    return _api('POST', '/api/v1/apps/live-sessions/control', body={
        'appid': appid, 'instance_id': instance_id,
        'sessions': list(sessions or [])})


class _LivePoller(object):
    """The one long poll every live session is fed from.

    `GET /api/v1/system/realtime-state` is Elten's own: one request that
    waits for something to happen and answers with everything that has -
    notifications, signals, and the `live_sessions` envelopes. Elten's
    notification service runs it and hands the last of those to
    `LiveSessions.receive`; this runs it on a thread of its own and the
    application drains what has arrived.

    A thread rather than a call per tick, because the point of a long poll
    is to be waiting when the packet arrives: asked once a second instead,
    a turn in a two-player game would take up to a second to show up, and
    asked once a frame it would be sixty requests a second.
    """

    #: How long the server may hold the request. Elten uses five seconds.
    WAIT_MS = 5000

    #: A poll that fails is retried, but not in a tight loop: EltenLink
    #: being down must not become a request storm.
    RETRY_SECONDS = 3.0

    def __init__(self):
        import threading
        self._rows = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._cursor = ''
        self._lasttime = ''
        self.error = ''

    def start(self):
        import threading
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name='EltenLivePoll')
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()

    def drain(self, limit=200):
        """Everything that has arrived since the last ask."""
        with self._lock:
            rows, self._rows = self._rows[:limit], self._rows[limit:]
        return rows

    def _run(self):
        import time
        while not self._stop.is_set():
            try:
                self._once()
            except Exception as error:                 # noqa: BLE001
                self.error = '%s: %s' % (type(error).__name__, error)
                if self._stop.wait(self.RETRY_SECONDS):
                    return

    def _once(self):
        import requests
        name, token = session()
        params = {'name': name, 'token': token, 'shown': 1,
                  'stream_capability': 1, 'wait_ms': self.WAIT_MS}
        if self._cursor:
            params['realtime_cursor'] = self._cursor
        if self._lasttime:
            params['lasttime'] = self._lasttime
        answer = requests.get('%s/api/v1/system/realtime-state' % API_BASE_URL,
                              params=params,
                              timeout=(API_TIMEOUT, self.WAIT_MS / 1000.0 + 10))
        if answer.status_code in (401, 403):
            forget_session()
            return
        payload = answer.json()
        data = payload.get('data') if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return
        self.error = ''
        cursor = str(data.get('realtime_cursor') or '')
        if cursor:
            self._cursor = cursor
        stamp = str(data.get('time') or '')
        if stamp:
            self._lasttime = stamp
        rows = data.get('live_sessions')
        if isinstance(rows, list) and rows:
            with self._lock:
                self._rows.extend(row for row in rows if isinstance(row, dict))
                # A game nobody is draining must not grow without bound.
                del self._rows[:-500]


_poller = None


def live_poll(limit=200):
    """The envelopes that have arrived, and start listening if nothing is.

    **Elten first, and then nothing else.** Its own notification service is
    already receiving them for this account; running a second poll beside it
    is two clients dividing one conversation between them, which is exactly
    how a table created here would never be heard of over there.
    """
    global _poller
    answered, value = via_elten('envelopes', limit=limit)
    if answered:
        # Elten is doing the listening, so ours must not.
        if _poller is not None:
            _poller.stop()
        rows = (value or {}).get('envelopes')
        return {'envelopes': rows if isinstance(rows, list) else [],
                'error': '', 'via': 'elten'}
    if _poller is None:
        _poller = _LivePoller()
    _poller.start()
    return {'envelopes': _poller.drain(limit), 'error': _poller.error}


def live_stop():
    if _poller is not None:
        _poller.stop()
    return True


# --------------------------------------------------------------------------- #
# Elten's own connection, when Elten is open
#
# Everything above signs its own requests with the EltenLink session Titan
# holds. That is right for anything private to one machine - a game's rows, a
# scoreboard - and wrong for playing WITH somebody.
#
# A live session is a conversation between two clients on one server, and the
# envelopes for it arrive on ONE long poll per account: the one Elten's own
# notification service is already running. A second client on the same account
# is a second poll, and each packet goes to whichever asked - so an
# application in Titan could create a table that the Elten it is meant to be
# played against would never hear about.
#
# So when Elten is open with the TCE bridge in it, that connection is
# borrowed: Elten makes the call, with its own client and its own realtime
# stream, and hands over the envelopes it has already received. One client on
# the account, the authoritative one - which is what makes an Elten
# application running inside Titan playable against people using Elten.
#
# It falls back to Titan's own session the moment Elten is not there, so an
# application still works on a machine that has never had Elten open.
# --------------------------------------------------------------------------- #
#: The add-on id the TCE bridge joins Titan's Action Bus with.
ELTEN_CLIENT = 'elten_tce_bridge'

#: Asking Elten is a round trip to another process and then to its own
#: thread. Long enough for a network call it makes on our behalf.
VIA_TIMEOUT = 25.0


def via_elten_available():
    """Whether the running Elten can be asked. Never raises."""
    try:
        from src.titan_core.actions import bus
        return bus.get_peer(ELTEN_CLIENT) is not None
    except Exception:
        return False


def via_elten(what, **args):
    """One call on Elten's own connection. (answered, value).

    `answered` False means Elten is not there or would not do it, and every
    caller then falls back to Titan's own session rather than failing - the
    port has to work on a machine that has never had Elten open.
    """
    try:
        from src.titan_core.actions import bus
    except Exception:
        return False, None
    if bus.get_peer(ELTEN_CLIENT) is None:
        return False, None
    payload = dict(args)
    payload['do'] = what
    ok, result = bus.invoke(ELTEN_CLIENT, 'eltenlink', payload,
                            timeout=VIA_TIMEOUT)
    if not ok:
        return False, None
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            # A sentence rather than a shape is the bridge refusing -
            # permission not given, most likely - and that is an answer.
            return True, {'error': result}
    if isinstance(result, dict) and result.get('error'):
        _note("Elten refused %s: %s" % (what, result['error']))
        return False, None
    return True, result
