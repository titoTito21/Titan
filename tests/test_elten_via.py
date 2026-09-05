"""Elten's own connection, borrowed by the port when Elten is open.

A live session is a conversation between two clients on one server, and its
envelopes arrive on ONE long poll per account - the one Elten's own
notification service is already running. A second client on the same account
is a second poll and each packet goes to whichever asked, so a table created
in Titan could be one the Elten it is meant to be played against never hears
about.

    python tests/test_elten_via.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'components', 'elten_bridge'))

from eltenkit import eltenlink


class Base(unittest.TestCase):
    def setUp(self):
        self.asked = []
        self.direct = []
        self._via = eltenlink.via_elten
        self._api = eltenlink._api

        def api(method, path, params=None, body=None):
            self.direct.append((method, path))
            return {'row': {'id': 1}}
        eltenlink._api = api

    def tearDown(self):
        eltenlink.via_elten = self._via
        eltenlink._api = self._api

    def elten_is_open(self, answers=None):
        answers = answers or {}

        def via(what, **args):
            self.asked.append((what, args))
            if what not in answers:
                return True, {}
            return True, answers[what]
        eltenlink.via_elten = via

    def elten_is_shut(self):
        eltenlink.via_elten = lambda what, **args: (False, None)


class WhenEltenIsOpen(Base):
    def test_every_live_call_goes_through_it(self):
        self.elten_is_open()
        eltenlink.live_create('app', 'inst')
        eltenlink.live_invite('s', 'p', 'dawid')
        eltenlink.live_accept('s', 'app', 'inst')
        eltenlink.live_reject('s', 'app')
        eltenlink.live_send('s', 'p', {'x': 1}, 'm1')
        eltenlink.live_leave('s', 'p')
        eltenlink.live_close('s', 'p')
        eltenlink.live_control('app', 'inst', [])
        eltenlink.signal_send('app', 'dawid', {'t': 1})
        self.assertEqual(
            [what for what, _args in self.asked],
            ['live_create', 'live_invite', 'live_accept', 'live_reject',
             'live_send', 'live_leave', 'live_close', 'live_control',
             'signal'])
        self.assertEqual(self.direct, [],
                         'a call went out on Titan\'s own session as well')

    def test_the_envelopes_are_eltens_and_ours_stops_listening(self):
        """Two polls on one account divide the conversation between them."""
        self.elten_is_open({'envelopes': {'envelopes': [{'kind': 'events'}]}})
        stopped = []
        eltenlink._poller = type('P', (), {
            'stop': lambda self: stopped.append(True),
            'start': lambda self: None,
            'drain': lambda self, limit: [{'kind': 'ours'}],
            'error': ''})()
        answer = eltenlink.live_poll()
        self.assertEqual(answer['envelopes'], [{'kind': 'events'}])
        self.assertEqual(answer.get('via'), 'elten')
        self.assertTrue(stopped, 'our own poll was left running beside it')
        eltenlink._poller = None


class WhenEltenIsShut(Base):
    def test_it_falls_back_to_titans_own_session(self):
        """The port has to work on a machine that has never had Elten
        open - that is what it is for."""
        self.elten_is_shut()
        eltenlink.live_create('app', 'inst')
        eltenlink.signal_send('app', 'dawid', {})
        self.assertEqual(
            [path for _method, path in self.direct],
            ['/api/v1/apps/live-sessions', '/api/v1/apps/signals'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
