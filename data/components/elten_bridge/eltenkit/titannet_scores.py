# -*- coding: utf-8 -*-
"""A real, SHARED scoreboard for Elten games - on Titan-Net.

Copyright (C) 2026 titosoft. Part of the Elten API bridge, licensed under
the GNU General Public License version 3 or later.

Some Elten games keep their scores in a **protected** app table on
EltenLink - a table the server accepts writes to only from Elten's own
signed launcher (`launcher/src/stamp.cpp`). That stamp is an anti-forgery
gate: it certifies "a genuine Elten launcher, on this hardware, for this
user", so the scores on Elten's global leaderboards can only come from
genuine Elten. Titan is not that launcher and does not pretend to be one -
minting a stamp would be writing Titan-played scores onto somebody else's
global leaderboard through the check that exists to stop exactly that.

So a game whose Elten leaderboard is closed to Titan gets a real
scoreboard that IS Titan's, the same way Cling's games do: a shared table
on Titan-Net, written as the Titan-Net account the user already has,
readable by every Titan player of that game. People playing in Titan
compare their scores with each other - honestly, on Titan's own board,
not faked onto Elten's.

An UNPROTECTED Elten table is used directly and is not touched by any of
this: that is the real Elten leaderboard and it already works.
"""

import re
import time

#: One namespace for every Elten game's Titan-Net scoreboard.
SLUG = 'elten_apps'


def _key(uuid, table):
    """A Titan-Net key for one game's one table.

    The uuid keeps two games apart; the table name keeps a game's own
    tables apart. Both are squeezed to what a key may hold.
    """
    raw = '%s__%s' % (str(uuid or ''), str(table or ''))
    return re.sub(r'[^A-Za-z0-9_.-]', '_', raw)[:120]


def _client():
    """Titan-Net's headless client, or `(None, why)`.

    The same one the Titan-Net action tools use - it signs in with the
    credentials Titan already has when "log me in automatically" is on,
    so a game shares a score with no window open.
    """
    try:
        from src.ai.tools import titannet_tools
        return titannet_tools._client()
    except Exception as error:
        return None, 'Titan-Net is not available here: %s' % error


def account_name():
    """Who the score is shared as, or ''."""
    client, _error = _client()
    return str(getattr(client, 'username', '') or '') if client else ''


def available():
    """Whether there is a Titan-Net account to share as, without a round trip."""
    try:
        from src.ai.tools import titannet_tools
        name, password = titannet_tools.saved_credentials()
        if name and password:
            return True
        client = titannet_tools._titan_net_client()
        return bool(client is not None and getattr(client, 'username', None))
    except Exception:
        return False


def _rows(client, uuid, table):
    answer = client.extension_data_get(SLUG, _key(uuid, table))
    value = answer.get('value') if isinstance(answer, dict) else None
    return [row for row in value if isinstance(row, dict)] \
        if isinstance(value, list) else []


def select(uuid, table, where=None, order=None, limit=None, offset=None):
    """Read the shared table - filtered and ordered the way Elten's is.

    `where` is equality on the game's own columns, `order` is
    `[field, "asc"|"desc"]`. The rows carry `__insertion_user` and
    `__insertion_time` beside the game's values, which is the shape
    Elten's own tables answer with, so a game reads them unchanged.
    """
    client, error = _client()
    if client is None:
        raise RuntimeError(error or 'Titan-Net is not signed in')
    rows = _rows(client, uuid, table)
    if isinstance(where, dict):
        rows = [row for row in rows
                if all(row.get(str(k)) == v for k, v in where.items())]
    if isinstance(order, (list, tuple)) and order:
        field = str(order[0])
        descending = len(order) > 1 and str(order[1]).lower() == 'desc'
        rows = sorted(rows, key=lambda row: _sortable(row.get(field)),
                      reverse=descending)
    start = int(offset) if offset else 0
    if start:
        rows = rows[start:]
    if limit:
        rows = rows[:int(limit)]
    return rows


def insert(uuid, table, values):
    """Add one row, as the Titan-Net user, best-effort under a race.

    `extension_data` is one shared blob, so two players writing at the
    same instant can lose one of each other's rows - which for a
    scoreboard is a score not shown rather than anything broken, and is
    the same bargain Cling's shared board makes. The table is capped so
    it cannot grow without bound.
    """
    client, error = _client()
    if client is None:
        raise RuntimeError(error or 'Titan-Net is not signed in')
    name = str(getattr(client, 'username', '') or '') or 'player'
    row = dict(values) if isinstance(values, dict) else {'value': values}
    row.setdefault('__insertion_user', name)
    row.setdefault('__insertion_time', int(time.time()))
    row['__id'] = int(time.time() * 1000)
    rows = _rows(client, uuid, table)
    rows.append(row)
    rows = rows[-500:]
    result = client.extension_data_set(SLUG, _key(uuid, table), rows)
    if isinstance(result, dict) and not result.get('success'):
        raise RuntimeError(str(result.get('error')
                               or result.get('message') or 'refused'))
    return row


def _sortable(value):
    if isinstance(value, (int, float)):
        return (0, value, '')
    try:
        return (0, float(value), '')
    except (TypeError, ValueError):
        return (1, 0.0, str(value))
