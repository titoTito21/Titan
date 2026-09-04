# -*- coding: utf-8 -*-
"""What a Cling application remembers between runs.

Klango kept a profile per user with an `.sdb` per application; Cling keeps a
directory per profile with a JSON file per application, under Titan's own
per-user data directory.  The application's own folder is never written to: it
may be read-only, it may be a packaged `.TCD` that is extracted into a cache
that is thrown away, and a game that stored the high scores next to itself
would lose them the first time it was reinstalled.
"""

import json
import os
import threading
import time

DEFAULT_PROFILE = 'default'
_LOCK = threading.RLock()


def root():
    """`.../titosoft/Titan/cling/` - where every profile lives."""
    try:
        from src.platform_utils import get_user_resource_path
        base = get_user_resource_path('cling')
    except Exception:
        import sys
        if sys.platform == 'win32':
            home = os.getenv('APPDATA', os.path.expanduser('~'))
        elif sys.platform == 'darwin':
            home = os.path.expanduser('~/Library/Application Support')
        else:
            home = os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
        base = os.path.join(home, 'titosoft', 'Titan', 'cling')
    return base


def profiles(base=None):
    base = os.path.join(base or root(), 'profiles')
    try:
        names = sorted(name for name in os.listdir(base)
                       if os.path.isdir(os.path.join(base, name)))
    except OSError:
        names = []
    return names or [DEFAULT_PROFILE]


class Store(object):
    """One application's saved state, in one profile."""

    def __init__(self, app_id, profile=DEFAULT_PROFILE, base=None):
        self.app_id = app_id or 'unknown'
        self.profile = profile or DEFAULT_PROFILE
        self.dir = os.path.join(base or root(), 'profiles', self.profile)
        self.path = os.path.join(self.dir, '%s.json' % _safe(self.app_id))
        self._data = None

    # ------------------------------------------------------------- reading
    def _load(self):
        if self._data is not None:
            return self._data
        data = {}
        try:
            with open(self.path, 'r', encoding='utf-8') as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            data = {}
        self._data = data
        return data

    def get(self, key, default=None):
        return self._load().get(key, default)

    def all(self):
        return dict(self._load())

    # ------------------------------------------------------------- writing
    def set(self, key, value):
        with _LOCK:
            self._load()[key] = value
            self._write()
        return value

    def update(self, values):
        with _LOCK:
            self._load().update(values or {})
            self._write()

    def clear(self):
        with _LOCK:
            self._data = {}
            self._write()

    def _write(self):
        try:
            os.makedirs(self.dir, exist_ok=True)
            # Written beside and moved into place: a game interrupted while it
            # is saving must not be a game whose scores are half a file.
            temporary = self.path + '.tmp'
            with open(temporary, 'w', encoding='utf-8') as handle:
                json.dump(self._data, handle, ensure_ascii=False, indent=1,
                          sort_keys=True)
            os.replace(temporary, self.path)
        except OSError as error:
            print('[cling] could not save %s: %s' % (self.path, error))

    # --------------------------------------------------------- high scores
    def scores(self, table='default'):
        tables = self._load().get('scores') or {}
        return list(tables.get(table) or [])

    def record_score(self, points, name='', table='default', keep=10,
                     extra=None):
        """Add a score and answer with the position it took, 1-based, or 0.

        Answering with the position is what lets a game say "a new best" only
        when it is true - a game that congratulates every player who finishes
        has told them nothing.
        """
        entry = {'points': int(points), 'name': name or '',
                 'when': int(time.time())}
        if extra:
            entry.update(extra)
        with _LOCK:
            data = self._load()
            tables = data.setdefault('scores', {})
            rows = list(tables.get(table) or [])
            rows.append(entry)
            rows.sort(key=lambda row: (-int(row.get('points', 0)),
                                       int(row.get('when', 0))))
            rows = rows[:max(1, int(keep))]
            tables[table] = rows
            self._write()
        return (rows.index(entry) + 1) if entry in rows else 0

    def best(self, table='default'):
        rows = self.scores(table)
        return int(rows[0].get('points', 0)) if rows else 0


def _safe(name):
    return ''.join(char if (char.isalnum() or char in '-_.') else '_'
                   for char in str(name))[:80] or 'app'
