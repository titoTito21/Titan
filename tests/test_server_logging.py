# -*- coding: utf-8 -*-
"""The logs really get written, and the audit trail really answers.

Run it directly (`python tests/test_server_logging.py`).

This exists because of a failure that was invisible for five months:
`logs/main.log` and `logs/http_server.log` were 0 bytes from April to
September, because `logging.basicConfig` configures the root logger the
FIRST time it is called and never again - while the `FileHandler` in its
argument list is constructed, and opened, regardless. Two of the three
modules created their log file and had their handler thrown away.

Nothing here reaches the network, the production server or the database.
"""

import io
import json
import logging
import os
import shutil
import sys
import tempfile
import unittest

import atexit as _atexit

#: Temporary directories this run made, removed when it ends.
#:
#: Measured: this suite left 6 directories behind per run, one per `mkdtemp` that
#: nothing removed, and they accumulate for ever - thousands had built up in
#: %TEMP%. Registered at exit rather than per test so a FAILING test cleans
#: up too.
_SCRATCH = []


def scratch(prefix=None):
    """A temporary directory that is removed when the run ends."""
    path = tempfile.mkdtemp(**({'prefix': prefix} if prefix else {}))
    _SCRATCH.append(path)
    return path


@_atexit.register
def _clear_scratch():
    while _SCRATCH:
        shutil.rmtree(_SCRATCH.pop(), ignore_errors=True)


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVER = os.path.join(ROOT, 'titan-net server')
if SERVER not in sys.path:
    sys.path.insert(0, SERVER)

import logging_setup                                          # noqa: E402


class TheLogsAreReallyWritten(unittest.TestCase):
    """Not "a handler was added" - written, with bytes in the file."""

    def setUp(self):
        self.folder = scratch('titanlogs_')
        self.was = logging_setup.FOLDER
        logging_setup.FOLDER = self.folder
        self.addCleanup(setattr, logging_setup, 'FOLDER', self.was)
        self.addCleanup(shutil.rmtree, self.folder, True)
        self._forget()
        # **Registered HERE, not inside `_forget`.** A cleanup that adds
        # itself as a cleanup is a list that never empties: unittest runs
        # them until there are none left, and each run put another one on.
        # The suite hung for ever, which from the outside looks exactly
        # like the code under test being slow.
        self.addCleanup(self._forget)

    def _forget(self):
        for name in ('TitanNetMain', 'TitanNetHTTP', 'TitanNetServer',
                     'TitanNetAudit', 'A', 'B', 'C'):
            logger = logging.getLogger(name)
            for handler in list(logger.handlers):
                try:
                    handler.close()
                except Exception:                    # noqa: BLE001
                    pass
                logger.removeHandler(handler)

    def _read(self, name):
        path = os.path.join(self.folder, name)
        if not os.path.exists(path):
            return None
        with io.open(path, encoding='utf-8') as handle:
            return handle.read()

    def test_all_three_write_whatever_is_imported_first(self):
        """The whole bug: whichever module lost the race wrote nothing."""
        one = logging_setup.configure('A', 'a.log')
        two = logging_setup.configure('B', 'b.log')
        three = logging_setup.configure('C', 'c.log')
        one.info('first')
        two.info('second')
        three.info('third')
        for name, said in (('a.log', 'first'), ('b.log', 'second'),
                           ('c.log', 'third')):
            text = self._read(name)
            self.assertIsNotNone(text, name + ' was never created')
            self.assertIn(said, text, name + ' is empty')

    def test_a_log_is_not_zero_bytes(self):
        """The exact shape of the failure, asked the exact way."""
        logger = logging_setup.configure('A', 'a.log')
        logger.info('something')
        self.assertGreater(os.path.getsize(os.path.join(self.folder, 'a.log')),
                           0)

    def test_configuring_twice_does_not_double_every_line(self):
        logger = logging_setup.configure('A', 'a.log')
        logging_setup.configure('A', 'a.log')
        logger.info('once')
        self.assertEqual(self._read('a.log').count('once'), 1)

    def test_the_console_handler_is_added_once(self):
        """`StandardOutput=journal` is how `journalctl -u titan-net` works,
        and nothing here may take it away - or add it five times."""
        root = logging.getLogger()
        before = [h for h in root.handlers
                  if isinstance(h, logging.StreamHandler)]
        for handler in before:
            root.removeHandler(handler)
        self.addCleanup(lambda: [root.addHandler(h) for h in before])
        logging_setup.configure('A', 'a.log')
        logging_setup.configure('B', 'b.log')
        logging_setup.configure('C', 'c.log')
        streams = [h for h in root.handlers
                   if isinstance(h, logging.StreamHandler)]
        self.assertEqual(len(streams), 1, streams)


class TheAuditTrailAnswersTheQuestion(unittest.TestCase):
    """"Has anybody else been signing in as this account?"

    The server keeps `users.last_login` and overwrites it every time, so
    that question had no answer at all - which is what was found when it
    was really asked about one.
    """

    def setUp(self):
        self.folder = scratch('titanaudit_')
        self.was = logging_setup.FOLDER
        logging_setup.FOLDER = self.folder
        self.addCleanup(setattr, logging_setup, 'FOLDER', self.was)
        self.addCleanup(shutil.rmtree, self.folder, True)
        logger = logging.getLogger('TitanNetAudit')
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)

    def _rows(self):
        path = os.path.join(self.folder, 'audit.log')
        if not os.path.exists(path):
            return []
        with io.open(path, encoding='utf-8') as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_one_line_per_event_and_it_is_json(self):
        logging_setup.audit('login', username='ala', user_id=3,
                            ip='1.2.3.4')
        logging_setup.audit('login_failed', username='ala', ip='5.6.7.8')
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['event'], 'login')
        self.assertEqual(rows[0]['username'], 'ala')
        self.assertEqual(rows[0]['ip'], '1.2.3.4')
        self.assertEqual(rows[1]['event'], 'login_failed')

    def test_every_row_says_when(self):
        logging_setup.audit('login', username='ala')
        row = self._rows()[0]
        self.assertIn('at', row)
        self.assertIsInstance(row['ts'], int)

    def test_a_secret_is_never_written_down(self):
        """A log kept for a year and a half is the worst place for one,
        and the field a caller passes by mistake is the way it gets there."""
        logging_setup.audit('login', username='ala', password='hunter2',
                            token='abc', session='xyz', api_key='k',
                            password_hash='$argon2id$...', auth='bearer')
        row = self._rows()[0]
        self.assertEqual(row['username'], 'ala')
        for gone in ('password', 'token', 'session', 'api_key',
                     'password_hash', 'auth'):
            self.assertNotIn(gone, row, gone)
        text = json.dumps(row)
        for secret in ('hunter2', 'abc', 'xyz', 'argon2id', 'bearer'):
            self.assertNotIn(secret, text, secret)

    def test_it_never_raises_whatever_it_is_handed(self):
        """It is called from the login path: an exception there is a
        server that cannot sign anybody in."""
        logging_setup.audit('login', username=object(), ip=None,
                            weird={'a': 1}, number=5, flag=True)
        self.assertEqual(len(self._rows()), 1)

    def test_it_does_not_answer_to_the_root_logger(self):
        """A change to the root's level or handlers quietened every other
        log here; this one must be out of reach of that."""
        logger = logging_setup._audit_logger()
        self.assertFalse(logger.propagate)

    def test_the_login_path_really_calls_it(self):
        """A trail nothing writes to is the bug this replaces."""
        with io.open(os.path.join(SERVER, 'server.py'),
                     encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn("logging_setup.audit('login'", source)
        self.assertIn("logging_setup.audit('login_failed'", source)

    def test_no_module_configures_logging_the_broken_way_any_more(self):
        """`basicConfig` in a second module is the whole failure."""
        for name in ('main.py', 'server.py', 'http_server.py'):
            with io.open(os.path.join(SERVER, name),
                         encoding='utf-8') as handle:
                source = handle.read()
            self.assertNotIn('logging.basicConfig', source, name)
            self.assertIn('logging_setup.configure', source, name)

    def test_the_report_says_what_is_really_being_written(self):
        """Being able to ASK is half the fix: the failure was invisible."""
        logging_setup.configure('TitanNetMain', 'main.log').info('x')
        found = logging_setup.report()
        self.assertIn('TitanNetMain', found)
        self.assertGreater(found['TitanNetMain']['files'].get('main.log', 0), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
