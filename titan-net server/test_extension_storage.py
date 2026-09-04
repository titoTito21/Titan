#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What an extension may keep on the server, and which extensions exist.

Both of these were found by Cling - Titan's Klango subsystem - being the first
thing to use extension storage for something that is not a string, and the
first thing shipped inside Titan to want storage on the server at all:

- **a value that is not a string never reached the database.**  A high-score
  table is a list of rows; SQLite binds text, numbers and blobs, so the list
  reached the driver and failed there, which the client saw as HTTP 500.
- **`/api/extensions/<slug>/data/<key>` refuses a slug that is not an ACTIVE
  extension**, and nothing had ever created one for a part of Titan itself.
  Every call answered "Active extension not found": scores were sent and
  never arrived, and the shared table was always empty.

Run it directly: `python test_extension_storage.py`.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:                                                    # pragma: no cover
    import argon2                                       # noqa: F401
except ImportError:
    # `models` imports the password hasher at the top and nothing here goes
    # near a password. A developer's machine is not the production server and
    # a test that cannot run there is a test nobody runs.
    import types

    _argon2 = types.ModuleType('argon2')
    _argon2.PasswordHasher = object
    _exceptions = types.ModuleType('argon2.exceptions')

    class _NotOurProblem(Exception):
        pass

    for _name in ('VerifyMismatchError', 'InvalidHash', 'VerificationError'):
        setattr(_exceptions, _name, _NotOurProblem)
    _argon2.exceptions = _exceptions
    sys.modules['argon2'] = _argon2
    sys.modules['argon2.exceptions'] = _exceptions

from models import Database


class TheEncoding(unittest.TestCase):
    """A value goes in as it was given and comes back as it was given."""

    def test_a_string_is_stored_exactly_as_it_was(self):
        """Everything already in the database is a string, and must read back
        byte for byte - which is why the marker is a control character no
        earlier value can begin with."""
        for value in ('', 'hello', '123', '{"a": 1}', '[1, 2, 3]', 'null'):
            stored = Database._ext_storage_encode(value)
            self.assertEqual(stored, value)
            self.assertEqual(Database._ext_storage_decode(stored), value)

    def test_nothing_stays_nothing(self):
        self.assertIsNone(Database._ext_storage_encode(None))
        self.assertIsNone(Database._ext_storage_decode(None))

    def test_a_list_of_rows_survives_the_round_trip(self):
        """A shared high-score table, which is what made this necessary."""
        rows = [{'name': 'tito', 'points': 187, 'level': 3},
                {'name': 'anna', 'points': 120, 'level': 2}]
        stored = Database._ext_storage_encode(rows)
        self.assertIsInstance(stored, str)
        self.assertEqual(Database._ext_storage_decode(stored), rows)

    def test_a_dictionary_survives_the_round_trip(self):
        """A player's own records, which is the other thing Cling keeps."""
        records = {'1': 'level=3;gold=40', '2': ''}
        self.assertEqual(
            Database._ext_storage_decode(Database._ext_storage_encode(records)),
            records)

    def test_what_is_stored_can_be_bound_by_sqlite(self):
        """The whole point: the driver refused a list, and that is what the
        caller saw as a 500."""
        handle, path = tempfile.mkstemp(suffix='.db')
        os.close(handle)
        try:
            connection = sqlite3.connect(path)
            connection.execute('CREATE TABLE t (value TEXT)')
            for value in ([{'a': 1}], {'a': 1}, 'plain', None):
                connection.execute(
                    'INSERT INTO t (value) VALUES (?)',
                    (Database._ext_storage_encode(value),))
            connection.commit()
            back = [Database._ext_storage_decode(row[0])
                    for row in connection.execute('SELECT value FROM t')]
            connection.close()
            self.assertEqual(back, [[{'a': 1}], {'a': 1}, 'plain', None])
        finally:
            os.unlink(path)

    def test_a_marked_value_that_is_damaged_is_nothing_rather_than_a_crash(self):
        broken = Database._EXT_JSON_PREFIX + '{not json'
        self.assertIsNone(Database._ext_storage_decode(broken))


class TheBuiltinExtensions(unittest.TestCase):
    """The server's own extensions: created if absent, never overwritten."""

    SCHEMA = """
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,
                            username TEXT, is_admin INTEGER DEFAULT 0);
        CREATE TABLE extensions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL, description TEXT, author_id INTEGER NOT NULL,
            version TEXT DEFAULT '1.0', client_code TEXT, manifest TEXT,
            code_hash TEXT, kind TEXT NOT NULL DEFAULT 'single', bundle TEXT,
            entry TEXT, moderators_only INTEGER NOT NULL DEFAULT 0,
            allowed_regions TEXT, blocked_regions TEXT,
            status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, approved_by INTEGER, approved_at TEXT);
    """

    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(self.SCHEMA)
        # `_ensure_builtin_extensions` is deliberately written against a
        # cursor rather than against the whole Database, so it can be run
        # exactly as `init_database` runs it and nothing else has to exist.
        self.seed = Database.__dict__['_ensure_builtin_extensions']

    def tearDown(self):
        self.connection.close()

    def rows(self):
        return [dict(r) for r in
                self.connection.execute('SELECT * FROM extensions')]

    def test_cling_is_created_active_and_owned_by_an_admin(self):
        self.connection.execute(
            "INSERT INTO users (username, is_admin) VALUES ('somebody', 0)")
        self.connection.execute(
            "INSERT INTO users (username, is_admin) VALUES ('boss', 1)")
        self.seed(Database, self.connection.cursor())
        rows = self.rows()
        self.assertEqual([row['slug'] for row in rows], ['cling'])
        self.assertEqual(rows[0]['status'], 'active')
        self.assertEqual(rows[0]['author_id'], 2)

    def test_the_first_user_will_do_when_there_is_no_admin(self):
        self.connection.execute(
            "INSERT INTO users (username, is_admin) VALUES ('somebody', 0)")
        self.seed(Database, self.connection.cursor())
        self.assertEqual(self.rows()[0]['author_id'], 1)

    def test_a_server_with_no_accounts_yet_is_left_alone(self):
        """There is nobody to own it. The next start is the first one that
        could have used it, and does it then."""
        self.seed(Database, self.connection.cursor())
        self.assertEqual(self.rows(), [])

    def test_running_twice_creates_nothing_the_second_time(self):
        self.connection.execute(
            "INSERT INTO users (username, is_admin) VALUES ('boss', 1)")
        self.seed(Database, self.connection.cursor())
        self.seed(Database, self.connection.cursor())
        self.assertEqual(len(self.rows()), 1)

    def test_an_extension_somebody_has_changed_is_never_touched(self):
        """Only ever INSERT: a moderator who renamed it, or took it out of
        service, has said something, and this is not the place to overrule
        them."""
        self.connection.execute(
            "INSERT INTO users (username, is_admin) VALUES ('boss', 1)")
        self.connection.execute(
            "INSERT INTO extensions (slug, name, description, author_id, "
            "status, created_at, updated_at) VALUES "
            "('cling', 'Renamed', 'theirs', 1, 'pending', 'x', 'x')")
        self.seed(Database, self.connection.cursor())
        row = self.rows()[0]
        self.assertEqual(row['name'], 'Renamed')
        self.assertEqual(row['status'], 'pending')


if __name__ == '__main__':
    unittest.main(verbosity=2)
