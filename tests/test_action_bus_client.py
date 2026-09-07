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


class ReadingAndDrivingAreDifferentPermissions(unittest.TestCase):
    """An external client may always READ Titan; controlling it is asked
    for once, in Titan, and remembered.

    The line is the one this repository already drew for the TCE bridge's
    own `press_key`: reading tells somebody what is there, and Enter in a
    messenger sends the message. Nothing here puts a dialog up - `known`
    is answered from the settings, which is what the gate really reads.
    """

    CLIENT = 'test-consent-client'

    def setUp(self):
        from src.titan_core import client_consent
        self.consent = client_consent
        client_consent.forget(self.CLIENT)
        self.asked = []
        self._ask = client_consent.ask
        client_consent.ask = lambda who, label='': self.asked.append(who)

    def tearDown(self):
        self.consent.ask = self._ask
        self.consent.forget(self.CLIENT)

    def peer(self):
        return FakePeer(self.CLIENT, 'client', [], client=True)

    def bridge_call(self, call):
        import json
        return {'type': 'call', 'addon': 'titan', 'action': 'bridge',
                'args': {'request': json.dumps({'call': call, 'args': {}})}}

    # ------------------------------------------------------------ the line
    def test_reading_is_served_without_being_allowed(self):
        for call in ('hello', 'apps.list', 'app.screen', 'settings.screen',
                     'addons.list', 'ai.history'):
            self.assertEqual(
                bus._not_allowed_to_drive(self.peer(), self.bridge_call(call)),
                '', '%s only reads and must never need permission' % call)

    def test_changing_something_is_not(self):
        for call in ('addons.run', 'settings.set', 'ai.ask', 'app.press',
                     'app.open', 'speech.say', 'menu.run'):
            self.assertNotEqual(
                bus._not_allowed_to_drive(self.peer(), self.bridge_call(call)),
                '', '%s changes Titan and must be asked about' % call)

    def test_a_client_reporting_about_itself_is_not_driving(self):
        """The bridge's whole unprompted job: a message arrived in Elten,
        and here is what that client is. They reach `show_notification`,
        so Elten's news behaves like tReminder's - the sound, the reader,
        the Titan buffer. Behind the drive consent the most useful thing
        the bridge does would stop until a dialog was answered, and it
        would be answering a question about something else.
        """
        for call in ('notifications.add', 'client.report'):
            self.assertEqual(
                bus._not_allowed_to_drive(self.peer(), self.bridge_call(call)),
                '', '%s is a client reporting about itself' % call)

    def test_an_action_that_is_not_the_bridge_always_drives(self):
        """`titan.bridge` is one action carrying a whole surface, so the
        CALL inside it decides. Everything else is an add-on being told
        to do something."""
        self.assertTrue(bus._would_drive(
            {'type': 'call', 'addon': 'tedit', 'action': 'save'}))
        self.assertTrue(bus._would_drive({'type': 'sequence', 'steps': []}))

    def test_a_request_that_cannot_be_read_drives(self):
        """An unreadable request is not a reason to assume the safe half."""
        self.assertTrue(bus._would_drive(
            {'type': 'call', 'addon': 'titan', 'action': 'bridge',
             'args': {'request': 'not json at all'}}))

    # -------------------------------------------------------- the add-ons
    def test_an_addon_is_never_asked_about(self):
        """There is deliberately no permission wall between add-ons - a
        component driving a widget is what the Action API is for, and a
        wall here would break it."""
        tedit = FakePeer('tedit', 'app', [{'name': 'save'}])
        self.assertEqual(bus._not_allowed_to_drive(
            tedit, {'type': 'call', 'addon': 'tnotes', 'action': 'create'}), '')

    # -------------------------------------------------------- the answer
    def test_yes_is_remembered_and_can_be_taken_back(self):
        self.assertIsNone(self.consent.known(self.CLIENT))
        self.consent.remember(self.CLIENT, True)
        self.assertTrue(self.consent.known(self.CLIENT))
        self.assertEqual(bus._not_allowed_to_drive(
            self.peer(), self.bridge_call('addons.run')), '')
        self.assertTrue(self.consent.forget(self.CLIENT))
        self.assertIsNone(self.consent.known(self.CLIENT))

    def test_no_is_an_answer_and_says_where_to_change_it(self):
        self.consent.remember(self.CLIENT, False)
        refused = bus._not_allowed_to_drive(self.peer(),
                                            self.bridge_call('addons.run'))
        self.assertTrue(refused)
        self.assertEqual(self.asked, [],
                         'an answer already given is not asked again')

    def test_unanswered_refuses_and_asks(self):
        refused = bus._not_allowed_to_drive(self.peer(),
                                            self.bridge_call('addons.run'))
        self.assertTrue(refused)
        self.assertEqual(self.asked, [self.CLIENT])

    def test_an_id_from_outside_cannot_write_a_settings_line(self):
        """The id is whatever connected, which is not Titan's to trust,
        and the settings file is `key=value` a line at a time."""
        key = self.consent._key('evil=yes\n[general]\nlanguage')
        self.assertNotIn('=', key)
        self.assertNotIn('\n', key)
        self.assertNotIn('[', key)

    def test_nobody_to_ask_is_not_a_yes(self):
        """`run_on_gui` calls its function on the calling thread when wx
        has no running application - right for a handler, catastrophic
        here. A `wx.MessageDialog` raised with no Titan behind it
        answered by ITSELF, and a `yes` was written that no person had
        given. This test is that accident, and it really happened.
        """
        self.assertFalse(self.consent.on_screen(),
                         'a test runner is not a Titan somebody can answer in')
        self.assertIsNone(self.consent._dialog(self.CLIENT, 'a client'))
        self.assertIsNone(self.consent.known(self.CLIENT))

    def test_an_unanswered_question_is_never_remembered(self):
        self.consent._ask_now(self.CLIENT, 'a client')
        self.assertIsNone(self.consent.known(self.CLIENT),
                          'not answered is not an answer')

    def test_the_surface_says_what_needs_permission(self):
        """A doorway nobody can enumerate is a doorway a client guesses
        at, and every guess this bridge has cost was of that shape."""
        from src.titan_core import bridge_api
        told = bridge_api._capabilities({})
        self.assertIn('addons.run', told['consent']['needed_for'])
        self.assertIn('apps.list', told['read_only'])
        self.assertEqual(set(told['read_only']) - set(told['calls']), set())


class EltensNotificationsAreNotSharedByDefault(unittest.TestCase):
    """Telling the USER is not telling a MODEL.

    A notification pushed into Titan's notification centre stays on this
    machine - the sound, the reader, the buffer. Read BACK by Perun or
    Melitele it is the text of somebody's private message in a prompt at
    a model provider, so it is a switch of its own and it starts as no.

    **The failure mode of a privacy switch is a lie**, which is what
    these test: with sharing off the report carries an empty list, and an
    empty list read as "nothing is waiting" is not a refusal - it is a
    false answer to the question that was asked.
    """

    def setUp(self):
        from src.titan_core import elten_client_actions
        self.client = elten_client_actions

    def state(self, **rest):
        base = {'user': 'someone', 'name': 'Someone', 'version': '3.0.2'}
        base.update(rest)
        return base

    def test_refused_says_so_and_never_says_nothing_is_waiting(self):
        said = self.client._describe_status(
            self.state(shared_with_ai=False, notifications=[], news={}),
            '', live=True)
        self.assertIn('not sharing', said)
        self.assertNotIn('0 notification', said)

    def test_it_still_says_elten_is_running_and_who_is_signed_in(self):
        """The floor: that is what makes the bridge answerable at all,
        and it is not somebody's correspondence."""
        said = self.client._describe_status(
            self.state(shared_with_ai=False, notifications=[]), '', live=True)
        self.assertIn('someone', said.lower())
        self.assertIn('connected', said.lower())

    def test_the_lists_refuse_too(self):
        for read in (self.client._describe_notifications,
                     self.client._describe_news):
            self.assertNotIn('shared', read([], '') or '')
        self.assertTrue(self.client._not_shared(
            self.state(shared_with_ai=False)))

    def test_a_bridge_older_than_the_switch_is_not_read_as_a_refusal(self):
        """It does not send the field at all, and reading its silence as
        a no would replace every answer it CAN give with one it never
        made."""
        self.assertFalse(self.client._not_shared(self.state()))
        self.assertFalse(self.client._not_shared(None))

    def test_sharing_is_off_until_it_is_switched_on(self):
        """Read from the bridge's own defaults, so the two cannot drift."""
        import os
        import re
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        text = open(os.path.join(here, 'elten-tce-bridge', 'titan_prefs.rb'),
                    encoding='utf-8').read()
        found = re.search(r'"share_with_ai"\s*=>\s*(\w+)', text)
        self.assertIsNotNone(found, 'the bridge has no share_with_ai default')
        self.assertEqual(found.group(1), 'false',
                         "somebody's private messages must not go to a "
                         "model provider by default")


if __name__ == '__main__':
    unittest.main(verbosity=2)
