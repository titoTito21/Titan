# -*- coding: utf-8 -*-
"""Who is playing: the Klango account, answered with the Titan-Net one.

Klango applications have an account behind them - a name on a high-score
table, a login before a chat or a multiplayer game will start, a profile the
saved games belong to.  Cling does not have a Klango account to offer and must
never ask for one: the user of this subsystem already has an identity on this
desktop, and it is their **Titan-Net** account.  So that is the account every
Cling application is given.

Three things follow, and all three are what a user would expect:

* **The profile is the Titan-Net user name.**  Two people using one Windows
  account keep separate saves and separate scores, because they sign in to
  Titan-Net as themselves.  Nobody signed in gets `local`, which is a real
  profile that keeps working offline rather than a refusal.
* **Signing in is never asked for twice.**  A user who ticked "log me in
  automatically" on Titan-Net's own login screen has signed in; Cling uses
  those saved credentials headlessly, and an application that wants an account
  gets one with no window appearing.
* **Nothing is sent anywhere to get a name.**  `whoami()` answers from the
  live client or from the saved user name.  Only `publish_score` talks to the
  server, only when the user is really signed in, and a failure there is a
  score that stayed local - never a game that stops.
"""

import getpass
import os
import threading

#: The server-side namespace Cling's shared score tables live under.
EXTENSION_SLUG = 'cling'
#: The profile a player who has never signed in to Titan-Net plays under.
LOCAL_PROFILE = 'local'

_lock = threading.RLock()


class Account(object):
    """Who Cling thinks is playing, and how sure it is."""

    __slots__ = ('name', 'display_name', 'online', 'source')

    def __init__(self, name, display_name='', online=False, source='local'):
        self.name = name
        self.display_name = display_name or name
        self.online = online
        self.source = source          # 'client' / 'saved' / 'local'

    @property
    def profile(self):
        return _safe(self.name) or LOCAL_PROFILE

    def describe(self):
        if self.source == 'client':
            return 'Signed in to Titan-Net as %s.' % self.name
        if self.source == 'saved':
            return ('Titan-Net account %s (saved sign-in; the server has not '
                    'been contacted).' % self.name)
        return ('Nobody is signed in to Titan-Net, so this is the local '
                'profile. Scores and saves are kept on this machine.')

    def __repr__(self):                                  # pragma: no cover
        return '<Account %s %s>' % (self.name, self.source)


def _live_client():
    """The Titan-Net client Titan already has open, or None. Never raises."""
    try:
        from src.network.titan_net import get_active_titan_net_client
    except Exception:
        return None
    try:
        client = get_active_titan_net_client()
    except Exception:
        return None
    if client is not None and getattr(client, 'username', None):
        return client
    return None


def _saved_credentials():
    """What the user asked Titan-Net to remember, or ('', '')."""
    try:
        from src.settings.titan_im_config import load_titan_im_config
        config = load_titan_im_config() or {}
    except Exception:
        return '', ''
    return (str(config.get('titannet_username') or '').strip(),
            str(config.get('titannet_password') or ''))


def whoami():
    """The account a Cling application is playing under. Never raises."""
    client = _live_client()
    if client is not None:
        name = str(getattr(client, 'username', '') or '')
        return Account(name, name, online=True, source='client')
    username, _password = _saved_credentials()
    if username:
        return Account(username, username, online=False, source='saved')
    try:
        local = getpass.getuser()
    except Exception:
        local = ''
    return Account(LOCAL_PROFILE, local or LOCAL_PROFILE, online=False,
                   source='local')


def profile():
    """The store profile for the account playing - the Titan-Net user name."""
    return whoami().profile


def sign_in():
    """(account, error) - sign in headlessly with what the user already saved.

    This is what an application calls when it genuinely needs an account: a
    chat, a multiplayer table, an online score.  It never opens a window and
    never asks for a password: either the user ticked "log me in
    automatically" on Titan-Net, in which case they are signed in, or the
    answer is a sentence saying where to do it - once, in Titan's own login
    screen, not per application.
    """
    with _lock:
        client = _live_client()
        if client is not None:
            name = str(getattr(client, 'username', '') or '')
            return Account(name, name, online=True, source='client'), ''

        username, password = _saved_credentials()
        if not (username and password):
            return whoami(), ('This needs a Titan-Net account. Open Titan-Net '
                              'once and sign in with "log me in automatically" '
                              'ticked; every Cling application then uses that '
                              'account.')
        try:
            from src.network.titan_net import (TitanNetClient,
                                               register_active_titan_net_client,
                                               set_active_titan_logged_in)
        except Exception as error:
            return whoami(), 'Titan-Net is not available here: %s' % error
        try:
            fresh = TitanNetClient()
            result = fresh.login(username, password)
        except Exception as error:
            return whoami(), ('Could not sign in to Titan-Net as %s: %s'
                              % (username, error))
        if isinstance(result, dict) and not result.get('success'):
            detail = result.get('message') or result.get('error') or 'refused'
            return whoami(), ('Titan-Net refused the saved sign-in for %s: %s'
                              % (username, detail))
        # Published only once the sign-in really worked: registering a client
        # that then failed to log in would leave the whole program holding a
        # dead one.
        try:
            register_active_titan_net_client(fresh)
            set_active_titan_logged_in(True)
        except Exception:
            pass
        return Account(username, username, online=True, source='client'), ''


# ------------------------------------------------------- shared scoreboards
def publish_score(app_id, points, extra=None):
    """Put a score on the shared table for this application. Best effort.

    Returns (published, message).  A game must never wait on this and must
    never fail because of it: the score is already in the player's own store
    by the time this is called, so "the server was not there" is a sentence,
    not a loss.
    """
    account, error = sign_in()
    if not account.online:
        return False, error or 'not signed in to Titan-Net'
    client = _live_client()
    if client is None:
        return False, 'Titan-Net is not connected'
    key = _score_key(app_id)
    entry = {'name': account.name, 'points': int(points)}
    if extra:
        entry.update(extra)
    try:
        current = client.extension_data_get(EXTENSION_SLUG, key)
        rows = current.get('value') if isinstance(current, dict) else None
        rows = list(rows) if isinstance(rows, list) else []
        rows = [row for row in rows
                if isinstance(row, dict) and row.get('name') != account.name]
        rows.append(entry)
        rows.sort(key=lambda row: -int(row.get('points', 0)))
        result = client.extension_data_set(EXTENSION_SLUG, key, rows[:50])
    except Exception as failure:
        return False, 'the shared score table could not be reached: %s' % failure
    if isinstance(result, dict) and not result.get('success'):
        return False, str(result.get('error') or 'the server refused the score')
    return True, 'Score published to Titan-Net as %s.' % account.name


def leaderboard(app_id, limit=10):
    """The shared table, best first, or [] when there is nothing to show."""
    client = _live_client()
    if client is None:
        return []
    try:
        result = client.extension_data_get(EXTENSION_SLUG, _score_key(app_id))
    except Exception:
        return []
    rows = result.get('value') if isinstance(result, dict) else None
    if not isinstance(rows, list):
        return []
    clean = [row for row in rows if isinstance(row, dict)]
    clean.sort(key=lambda row: -int(row.get('points', 0) or 0))
    return clean[:max(1, int(limit))]


def _score_key(app_id):
    return 'scores_%s' % _safe(app_id)


def _safe(name):
    return ''.join(char if (char.isalnum() or char in '-_.') else '_'
                   for char in str(name or ''))[:60]


# ------------------------------------------------- the user's own records
# Klango kept a small per-user, per-application store on its own server
# (`_UserSRWrite` / `_UserSRRead`) - the place a game put a saved position or
# a setting it wanted the player to have on any machine.  That server is
# gone; Titan-Net's extension data is the same thing, so that is where these
# go.  A player who is not signed in still gets the records, out of their own
# profile - a save that only exists on a server the player cannot reach is a
# save they have lost.
def _record_key(app_id, user):
    return 'records_%s_%s' % (_safe(app_id), _safe(user))


def user_records(app_id, local_store=None):
    """Every record this player has for this application, as {index: data}."""
    account = whoami()
    client = _live_client() if account.online else None
    if client is not None:
        try:
            result = client.extension_data_get(EXTENSION_SLUG,
                                               _record_key(app_id, account.name))
            value = result.get('value') if isinstance(result, dict) else None
            if isinstance(value, dict):
                return dict(value)
        except Exception:
            pass
    if local_store is not None:
        kept = local_store.get('klango_records')
        if isinstance(kept, dict):
            return dict(kept)
    return {}


def write_user_record(app_id, index, data, local_store=None):
    """Keep one record. Locally first and always, then on Titan-Net."""
    records = user_records(app_id, local_store)
    records[str(index)] = data
    if local_store is not None:
        local_store.set('klango_records', records)
    account = whoami()
    if not account.online:
        return True
    client = _live_client()
    if client is None:
        return True
    try:
        client.extension_data_set(EXTENSION_SLUG,
                                  _record_key(app_id, account.name), records)
    except Exception:
        pass
    return True


def read_user_record(app_id, index=None, local_store=None):
    """One record, or every record when no index is named."""
    records = user_records(app_id, local_store)
    if index is None or index == '':
        return records
    return records.get(str(index))
