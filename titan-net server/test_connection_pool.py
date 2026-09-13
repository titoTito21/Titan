"""The pooled database connection, and the 500 that said nothing.

Production answered ``{"success": false, "error": ""}`` on every endpoint
that touched the database from the asyncio event loop thread, while every
endpoint that went through ``run_in_executor`` answered 200 - for as long as
the process lived. Two faults, one symptom:

  1. ``_PooledConn.close()`` is a deliberate no-op, so the real connection
     stays in ``Database._tls`` for the life of the thread. Nothing ever
     asked whether it still worked, so a connection that went bad was handed
     out again for every later query ON THAT THREAD and nowhere else - which
     from outside is a server that is half broken. SQLCipher's
     ``sqlite3Codec: deferred error condition`` surfaces as a bare
     ``MemoryError`` (see the ``_serialized_write`` iteration notes in
     models.py), and this had been seen on this server before.

  2. ``MemoryError`` is raised with no arguments, so ``str(e)`` is ``''`` -
     and 110 handlers reported exactly ``str(e)``. The one thing that would
     have identified the fault was the one thing thrown away.

Run directly: ``python test_connection_pool.py``. Nothing here reaches the
network and no test writes outside its own temporary directory.
"""

import asyncio
import logging
import os
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('LOCAL_MODE', '1')
os.environ.setdefault('DATABASE_KEY', '0' * 64)
logging.disable(logging.CRITICAL)

from models import Database                      # noqa: E402
from logging_setup import describe_error          # noqa: E402


class Poisoned:
    """A connection that behaves as SQLCipher's deferred error condition does."""

    def __getattr__(self, name):
        raise MemoryError()

    def execute(self, *a, **k):
        raise MemoryError()

    def cursor(self):
        raise MemoryError()

    def close(self):
        pass


class _DBCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Database(db_path=os.path.join(self.tmp, 't.db'))

    def tearDown(self):
        try:
            self.db.close_all()
        except Exception:
            pass
        Database._instances = {} if hasattr(Database, '_instances') else getattr(
            Database, '_instances', {})
        shutil.rmtree(self.tmp, ignore_errors=True)


class APooledConnectionThatDied(_DBCase):
    def test_a_healthy_connection_is_reused_not_reopened(self):
        """The pool must still be a pool: SQLCipher's KDF is the whole reason
        it exists, so a working connection is handed back unchanged."""
        self.db.get_connection()
        real = self.db._tls.conn
        for _ in range(5):
            self.db.get_connection()
        self.assertIs(self.db._tls.conn, real)

    def test_a_dead_connection_is_replaced_rather_than_handed_out(self):
        self.db.get_connection()
        dead = self.db._tls.conn
        dead.close()                     # the real handle is now unusable
        conn = self.db.get_connection()
        self.assertIsNot(self.db._tls.conn, dead)
        row = conn.cursor().execute('SELECT COUNT(*) AS n FROM users').fetchone()
        self.assertEqual(row['n'], 0)

    def test_a_connection_raising_MemoryError_is_replaced(self):
        """Production's actual fault. A MemoryError from the cipher layer must
        not become a permanent per-thread outage."""
        self.db.get_connection()
        self.db._tls.conn = Poisoned()
        conn = self.db.get_connection()
        row = conn.cursor().execute('SELECT COUNT(*) AS n FROM users').fetchone()
        self.assertEqual(row['n'], 0)

    def test_recovery_is_not_a_one_off(self):
        """It has to keep working, or the second failure is the outage."""
        for _ in range(3):
            self.db.get_connection()
            self.db._tls.conn = Poisoned()
            conn = self.db.get_connection()
            conn.cursor().execute('SELECT 1').fetchone()

    def test_the_probe_does_not_swallow_an_interrupt(self):
        """A probe that reported a healthy connection for a KeyboardInterrupt
        would stop the server shutting down."""
        class Interrupting:
            def execute(self, *a, **k):
                raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.db._connection_is_alive(Interrupting())


class AnErrorThatSaysWhichError(unittest.TestCase):
    def test_an_exception_with_no_message_still_names_itself(self):
        self.assertEqual(describe_error(MemoryError()), 'MemoryError')
        self.assertEqual(describe_error(TimeoutError()), 'TimeoutError')

    def test_a_message_is_kept_and_labelled(self):
        self.assertEqual(describe_error(ValueError('no such column')),
                         'ValueError: no such column')

    def test_it_is_never_empty(self):
        for exc in (MemoryError(), Exception(), Exception('   '),
                    ValueError(''), KeyError()):
            self.assertTrue(describe_error(exc).strip(),
                            f'{type(exc).__name__} rendered as blank')

    def test_an_exception_whose_str_raises_is_still_described(self):
        class Awkward(Exception):
            def __str__(self):
                raise RuntimeError('cannot render')
        self.assertEqual(describe_error(Awkward()), 'Awkward')

    def test_every_handler_reports_through_it(self):
        """The fault was 110 call sites each formatting the error themselves.
        A new handler written the old way puts the blank 500 straight back."""
        here = os.path.dirname(os.path.abspath(__file__))
        src = open(os.path.join(here, 'http_server.py'), encoding='utf-8').read()
        self.assertNotIn("'error': str(e)", src)
        self.assertIn('from logging_setup import describe_error', src)


class TheHandlersThatFailed(unittest.TestCase):
    """End to end, through the real aiohttp app, on the event loop thread -
    which is where production failed and where a unit test would not look."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Database(db_path=os.path.join(self.tmp, 't.db'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _get(self, path, poison=False):
        """One request through the real app. aiohttp binds an Application to
        the loop that first ran it, so the server is built inside the
        coroutine rather than in setUp."""
        from aiohttp.test_utils import TestServer, TestClient
        from http_server import TitanNetHTTPServer

        async def run():
            srv = TitanNetHTTPServer(host='127.0.0.1', port=0, db=self.db,
                                     upload_dir=os.path.join(self.tmp, 'up'))
            ts = TestServer(srv.app)
            await ts.start_server()
            cl = TestClient(ts)
            if poison:
                self.db.get_connection()
                self.db._tls.conn = Poisoned()
            r = await cl.get(path)
            body = await r.text()
            await cl.close()
            await ts.close()
            return r.status, body

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(run())
        finally:
            loop.close()

    def test_the_event_loop_thread_endpoints_answer(self):
        for path in ('/api/stats', '/api/repository/apps', '/api/search?q=a'):
            status, body = self._get(path)
            self.assertEqual(status, 200, f'{path} -> {body[:200]}')

    def test_a_poisoned_pool_no_longer_breaks_them(self):
        status, body = self._get('/api/stats', poison=True)
        self.assertEqual(status, 200, body[:200])
        self.assertIn('"success": true', body)

    def test_no_500_ever_carries_an_empty_error(self):
        self.assertNotIn('"error": ""', self._get('/api/stats', poison=True)[1])


class AndTheAuthorisationThatWasRequired(unittest.TestCase):
    """The other half of the same fault, and the half the user actually saw.

    ``verify_token`` is called synchronously on the event loop thread in 45
    of its 48 call sites, and it ends with ``except Exception: return None``.
    It reads the user out of the database (``get_user_by_id`` ->
    ``get_connection``), so a pooled connection that had gone bad made every
    authenticated request answer **401 "Authentication required"** - a real,
    logged-in user told their authorisation was needed, for as long as the
    process lived. Swallowing the exception is right (a token that cannot be
    checked is not a token that is good); caching the broken connection for
    ever was the fault.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = Database(db_path=os.path.join(self.tmp, 't.db'))
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username, password_hash, titan_number, "
                    "created_at, is_admin, role) VALUES "
                    "('realuser', 'x', 5001, '2026-01-01', 1, 'admin')")
        self.user_id = cur.lastrowid
        conn.commit()
        import auth_tokens
        self.token = auth_tokens.mint(self.user_id, 'realuser', 'admin')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _verify(self, poison):
        """Ask verify_token about a genuine signed token, as a handler does."""
        from http_server import TitanNetHTTPServer

        async def run():
            srv = TitanNetHTTPServer(host='127.0.0.1', port=0, db=self.db,
                                     upload_dir=os.path.join(self.tmp, 'up'))
            from aiohttp.test_utils import make_mocked_request
            request = make_mocked_request(
                'GET', '/api/sounds',
                headers={'Authorization': f'Bearer {self.token}'})
            if poison:
                self.db.get_connection()
                self.db._tls.conn = Poisoned()
            return srv.verify_token(request)

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(run())
        finally:
            loop.close()

    def test_a_real_token_is_accepted_normally(self):
        user = self._verify(poison=False)
        self.assertIsNotNone(user)
        self.assertEqual(user['username'], 'realuser')

    def test_a_real_token_is_still_accepted_when_the_pool_went_bad(self):
        """Before the fix this returned None, and the client was told
        'Authentication required' - which is what was reported."""
        user = self._verify(poison=True)
        self.assertIsNotNone(
            user, 'a genuine signed token was refused because the pooled '
                  'connection had died - the reported "authorisation is required"')
        self.assertEqual(user['username'], 'realuser')


if __name__ == '__main__':
    unittest.main(verbosity=2)
