"""An external client joining Titan, and leaving, is said out loud.

Two different things join the Action Bus. An ADD-ON serves actions - tEdit
says "here is open_file and save" and Titan calls into it - and the user
just opened it, so they know. A CLIENT serves nothing and only calls: it is
another program on the machine taking hold of Titan, and the Elten TCE
bridge is one. Nothing else on this desktop would tell the user that had
happened, so Titan says so.

    python tests/test_action_bus_client.py
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.titan_core.actions import bus


class FakePeer(object):
    def __init__(self, addon_id='someone', kind='app', actions=None,
                 client=False):
        self.addon_id = addon_id
        self.kind = kind
        self.actions = actions or []
        self.client = client
        self.pid = 4321


class WhoIsAClient(unittest.TestCase):
    def test_a_peer_that_says_it_is_a_client_is_one(self):
        self.assertTrue(bus._is_external_client(
            FakePeer(client=True, actions=[{'name': 'x'}])))

    def test_a_peer_serving_nothing_is_a_client(self):
        self.assertTrue(bus._is_external_client(FakePeer(actions=[])))

    def test_an_addon_that_serves_actions_is_not(self):
        """The one that matters: opening tEdit must not announce anything."""
        self.assertFalse(bus._is_external_client(
            FakePeer('tedit', 'app', [{'name': 'open_file'}])))

    def test_the_kind_is_read_too(self):
        self.assertTrue(bus._is_external_client(
            FakePeer(kind='client', actions=[{'name': 'x'}])))


class WhatIsSaid(unittest.TestCase):
    """The words and the sound, with nothing actually spoken or played."""

    def setUp(self):
        bus._announced.clear()
        self.said = []
        self.played = []
        import src.titan_core.stereo_speech as speech
        import src.titan_core.sound as sound
        self._speak = speech.speak_stereo
        self._play = sound.play_sound
        speech.speak_stereo = lambda text, **kw: self.said.append(text)
        sound.play_sound = lambda name, **kw: self.played.append(name)
        self.speech = speech
        self.sound = sound

    def tearDown(self):
        self.speech.speak_stereo = self._speak
        self.sound.play_sound = self._play
        bus._announced.clear()

    def _wait(self, count=1, seconds=2.0):
        deadline = time.time() + seconds
        while time.time() < deadline and len(self.said) < count:
            time.sleep(0.01)

    def test_a_client_joining_is_said(self):
        bus._announce_client(FakePeer('elten_tce_bridge', client=True), True)
        self._wait()
        self.assertEqual(len(self.said), 1)
        self.assertIn('client', self.said[0].lower() + 'client')
        self.assertEqual(self.played, ['system/sysprocess_open.ogg'])

    def test_a_client_leaving_is_said(self):
        bus._announce_client(FakePeer('elten_tce_bridge', client=True), False)
        self._wait()
        self.assertEqual(len(self.said), 1)
        self.assertEqual(self.played, ['system/sysprocess_close.ogg'])

    def test_an_addon_is_not_announced_at_all(self):
        bus._announce_client(
            FakePeer('tedit', 'app', [{'name': 'open_file'}]), True)
        time.sleep(0.2)
        self.assertEqual(self.said, [])
        self.assertEqual(self.played, [])

    def test_the_same_arrival_twice_is_one_arrival(self):
        """A client that loses the pipe and comes straight back has not
        arrived twice, and saying so is worse than saying nothing."""
        peer = FakePeer('elten_tce_bridge', client=True)
        bus._announce_client(peer, True)
        bus._announce_client(peer, True)
        self._wait()
        time.sleep(0.2)
        self.assertEqual(len(self.said), 1)

    def test_leaving_after_joining_is_still_said(self):
        """The debounce is per direction: a client that joins and then goes
        away has done two things, and both are news."""
        peer = FakePeer('elten_tce_bridge', client=True)
        bus._announce_client(peer, True)
        self._wait(1)
        bus._announce_client(peer, False)
        self._wait(2)
        self.assertEqual(len(self.said), 2)
        self.assertNotEqual(self.said[0], self.said[1])

    def test_speech_that_fails_does_not_take_the_bus_down(self):
        self.speech.speak_stereo = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError('no voice'))
        bus._announce_client(FakePeer('elten_tce_bridge', client=True), True)
        time.sleep(0.3)          # the point is that nothing raised in here


if __name__ == '__main__':
    unittest.main(verbosity=2)
