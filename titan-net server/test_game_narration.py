"""
Tests for game_narration.py - who says the AI's lines out loud.

No model, no network, no audio device and no API key: the relay's whole
job is deciding WHO speaks and making sure somebody always does, and that
is decided from messages, which is what these fake in.

Run directly:  python test_game_narration.py
"""

import asyncio
import sys
import time
import unittest

from game_narration import (
    NarrationRelay, FIRST_CHUNK_TIMEOUT_S, STALL_TIMEOUT_S, MAX_PENDING,
    MAX_CHUNK_B64,
)

HOST = 7
OTHER = 9
SESSION = 42


class Wire:
    """Everything the relay put on the wire, in order."""

    def __init__(self):
        self.room = []
        self.direct = []

    async def broadcast(self, session_id, message):
        self.room.append((session_id, message))

    async def to_user(self, user_id, message):
        self.direct.append((user_id, message))

    def of_type(self, wanted):
        return [m for _, m in self.room if m.get('type') == wanted]

    def requests(self):
        return [m for _, m in self.direct if m.get('type') == 'game_speak_request']


def relay(wire, *, host=HOST, direct=True):
    return NarrationRelay(
        session_id=SESSION,
        broadcast_cb=wire.broadcast,
        send_to_user_cb=(wire.to_user if direct else None),
        host_id=host,
    )


def run(coro):
    return asyncio.run(coro)


class TestHostCapability(unittest.TestCase):

    def test_nobody_narrates_until_the_host_says_so(self):
        wire = Wire()
        r = relay(wire)
        self.assertFalse(r.narrating)
        uid = run(r.say('The door creaks open.'))
        self.assertIsNone(uid, "a line must not wait on a host that never offered")
        self.assertEqual(wire.requests(), [])

    def test_host_offering_makes_it_narrate(self):
        wire = Wire()
        r = relay(wire)
        self.assertTrue(r.host_can_speak(HOST, True, voice='supertonic'))
        self.assertTrue(r.narrating)

    def test_only_the_host_may_offer(self):
        wire = Wire()
        r = relay(wire)
        self.assertFalse(r.host_can_speak(OTHER, True))
        self.assertFalse(r.narrating,
                         "another player must not be able to narrate the table")

    def test_host_leaving_stops_narration(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        r.host_gone(HOST)
        self.assertFalse(r.narrating)

    def test_another_player_leaving_changes_nothing(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        r.host_gone(OTHER)
        self.assertTrue(r.narrating)

    def test_a_new_host_has_to_offer_again(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        r.set_host(OTHER)
        self.assertFalse(r.narrating,
                         "the old host's voice does not carry over to a new one")

    def test_no_direct_channel_means_no_narration(self):
        # A server with no way to reach one user cannot ask anybody to
        # speak, however willing the host is.
        wire = Wire()
        r = relay(wire, direct=False)
        r._host_ready = True
        self.assertFalse(r.narrating)


class TestAsking(unittest.TestCase):

    def test_the_request_carries_the_line_and_reaches_the_host(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        uid = run(r.say('You hear footsteps.', actor='gm'))
        self.assertIsNotNone(uid)
        self.assertEqual(len(wire.direct), 1)
        user_id, msg = wire.direct[0]
        self.assertEqual(user_id, HOST)
        self.assertEqual(msg['type'], 'game_speak_request')
        self.assertEqual(msg['text'], 'You hear footsteps.')
        self.assertEqual(msg['utterance_id'], uid)
        self.assertEqual(msg['session_id'], SESSION)

    def test_an_empty_line_is_not_a_line(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        self.assertIsNone(run(r.say('   ')))
        self.assertEqual(wire.direct, [])

    def test_each_utterance_gets_its_own_id(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        ids = [run(r.say('line %d' % i)) for i in range(4)]
        self.assertEqual(len(set(ids)), 4)

    def test_a_host_falling_behind_hands_back_to_the_table(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        for i in range(MAX_PENDING):
            self.assertIsNotNone(run(r.say('line %d' % i)))
        self.assertIsNone(run(r.say('one too many')),
                          "a host that is not keeping up must not queue the table")


class TestRelaying(unittest.TestCase):

    def test_a_chunk_reaches_the_table_as_game_ai_audio(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        uid = run(r.say('Rain on the roof.'))
        result = run(r.on_chunk(HOST, {
            'utterance_id': uid, 'audio_b64': 'QUJD', 'mime_type': 'audio/wav',
        }))
        self.assertTrue(result['success'])
        audio = wire.of_type('game_ai_audio')
        self.assertEqual(len(audio), 1)
        self.assertEqual(audio[0]['audio_b64'], 'QUJD')
        self.assertEqual(audio[0]['utterance_id'], uid)
        self.assertEqual(audio[0]['session_id'], SESSION)

    def test_only_the_first_chunk_interrupts(self):
        # An interrupting line clears what is playing once; every chunk
        # after it must join on, or the sentence cuts itself off.
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        uid = run(r.say('Stop!', interrupt=True))
        for _ in range(3):
            run(r.on_chunk(HOST, {'utterance_id': uid, 'audio_b64': 'QUJD'}))
        flags = [m['interrupt'] for m in wire.of_type('game_ai_audio')]
        self.assertEqual(flags, [True, False, False])

    def test_a_stranger_cannot_play_audio_at_the_room(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        uid = run(r.say('A line.'))
        result = run(r.on_chunk(OTHER, {'utterance_id': uid, 'audio_b64': 'QUJD'}))
        self.assertFalse(result['success'])
        self.assertEqual(wire.of_type('game_ai_audio'), [])

    def test_an_unasked_for_utterance_is_refused(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        result = run(r.on_chunk(HOST, {'utterance_id': 'made-up', 'audio_b64': 'QUJD'}))
        self.assertFalse(result['success'])
        self.assertEqual(wire.of_type('game_ai_audio'), [])

    def test_an_oversized_chunk_is_refused(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        uid = run(r.say('A line.'))
        result = run(r.on_chunk(HOST, {
            'utterance_id': uid, 'audio_b64': 'A' * (MAX_CHUNK_B64 + 1),
        }))
        self.assertFalse(result['success'])
        self.assertEqual(wire.of_type('game_ai_audio'), [])

    def test_final_closes_the_utterance(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        uid = run(r.say('Done.'))
        run(r.on_chunk(HOST, {'utterance_id': uid, 'audio_b64': 'QUJD', 'final': True}))
        # A chunk after the end belongs to nothing.
        result = run(r.on_chunk(HOST, {'utterance_id': uid, 'audio_b64': 'QUJD'}))
        self.assertFalse(result['success'])
        self.assertEqual(r.stats['streamed'], 1)

    def test_a_final_with_no_audio_still_closes(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        uid = run(r.say('Done.'))
        run(r.on_chunk(HOST, {'utterance_id': uid, 'final': True}))
        self.assertEqual(r.status()['pending'], 0)


class TestFallingBackToTheTable(unittest.TestCase):

    def test_a_host_that_cannot_speak_hands_the_line_back(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        uid = run(r.say('The bridge groans.'))
        run(r.on_failed(HOST, {'utterance_id': uid, 'error': 'engine missing'}))
        local = wire.of_type('game_speak_locally')
        self.assertEqual(len(local), 1)
        self.assertEqual(local[0]['text'], 'The bridge groans.')
        self.assertEqual(local[0]['utterance_id'], uid)

    def test_the_local_line_is_not_a_second_copy_of_the_text(self):
        # game_ai_text already put the words in every player's log; the
        # fallback must not put them there again.
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        uid = run(r.say('Once.'))
        run(r.on_failed(HOST, {'utterance_id': uid}))
        self.assertEqual(wire.of_type('game_ai_text'), [])

    def test_a_line_is_never_handed_back_twice(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        uid = run(r.say('Once.'))
        run(r.on_failed(HOST, {'utterance_id': uid}))
        run(r.on_failed(HOST, {'utterance_id': uid}))
        self.assertEqual(len(wire.of_type('game_speak_locally')), 1)

    def test_a_stranger_cannot_declare_failure(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        uid = run(r.say('A line.'))
        result = run(r.on_failed(OTHER, {'utterance_id': uid}))
        self.assertFalse(result['success'])
        self.assertEqual(wire.of_type('game_speak_locally'), [])

    def test_silence_past_the_deadline_hands_the_line_back(self):
        async def scenario():
            wire = Wire()
            r = relay(wire)
            r.host_can_speak(HOST, True)
            await r.say('Nobody answers.')
            # Age the utterance rather than sleeping through the deadline:
            # a test that waits 3.5 s per case is a test nobody runs.
            for utt in r._pending.values():
                utt.requested_at -= (FIRST_CHUNK_TIMEOUT_S + 1)
            await asyncio.sleep(0.4)
            await r.stop()
            return wire
        wire = run(scenario())
        self.assertEqual(len(wire.of_type('game_speak_locally')), 1)

    def test_a_stall_mid_sentence_does_not_repeat_what_was_heard(self):
        # Some audio already played, so the line is partly said. Saying it
        # again from the beginning in a different voice is worse than
        # letting it end short.
        async def scenario():
            wire = Wire()
            r = relay(wire)
            r.host_can_speak(HOST, True)
            uid = await r.say('Half a sentence and then')
            await r.on_chunk(HOST, {'utterance_id': uid, 'audio_b64': 'QUJD'})
            for utt in r._pending.values():
                utt.requested_at -= (STALL_TIMEOUT_S + 1)
                utt.last_chunk_at = time.monotonic() - (STALL_TIMEOUT_S + 1)
            await asyncio.sleep(0.4)
            await r.stop()
            return wire
        wire = run(scenario())
        self.assertEqual(wire.of_type('game_speak_locally'), [])
        self.assertEqual(len(wire.of_type('game_ai_audio')), 1)

    def test_the_deadline_does_not_fire_on_a_line_being_spoken(self):
        async def scenario():
            wire = Wire()
            r = relay(wire)
            r.host_can_speak(HOST, True)
            uid = await r.say('Coming through fine.')
            for _ in range(3):
                await r.on_chunk(HOST, {'utterance_id': uid, 'audio_b64': 'QUJD'})
                await asyncio.sleep(0.15)
            await r.stop()
            return wire
        wire = run(scenario())
        self.assertEqual(wire.of_type('game_speak_locally'), [])


class TestTeardown(unittest.TestCase):

    def test_stopping_says_nothing_more(self):
        # The session has ended; narrating into it is talking to a room
        # that has gone.
        async def scenario():
            wire = Wire()
            r = relay(wire)
            r.host_can_speak(HOST, True)
            await r.say('Unfinished.')
            for utt in r._pending.values():
                utt.requested_at -= (FIRST_CHUNK_TIMEOUT_S + 1)
            await r.stop()
            await asyncio.sleep(0.4)
            return wire
        wire = run(scenario())
        self.assertEqual(wire.of_type('game_speak_locally'), [])

    def test_stopping_twice_is_fine(self):
        async def scenario():
            wire = Wire()
            r = relay(wire)
            await r.stop()
            await r.stop()
        run(scenario())

    def test_status_reports_what_happened(self):
        wire = Wire()
        r = relay(wire)
        r.host_can_speak(HOST, True, voice='eloquence')
        uid = run(r.say('A line.'))
        run(r.on_chunk(HOST, {'utterance_id': uid, 'audio_b64': 'QUJD', 'final': True}))
        st = r.status()
        self.assertEqual(st['host_id'], HOST)
        self.assertTrue(st['host_ready'])
        self.assertEqual(st['host_voice'], 'eloquence')
        self.assertEqual(st['pending'], 0)
        self.assertEqual(st['stats']['requested'], 1)
        self.assertEqual(st['stats']['streamed'], 1)

    def test_a_broadcast_that_throws_does_not_take_the_session_down(self):
        class Broken(Wire):
            async def broadcast(self, session_id, message):
                raise RuntimeError('socket gone')
        wire = Broken()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        uid = run(r.say('A line.'))
        # The failure is swallowed; the game carries on.
        run(r.on_failed(HOST, {'utterance_id': uid}))

    def test_a_request_that_cannot_be_sent_falls_back_at_once(self):
        class NoHost(Wire):
            async def to_user(self, user_id, message):
                raise RuntimeError('host disconnected')
        wire = NoHost()
        r = relay(wire)
        r.host_can_speak(HOST, True)
        self.assertIsNone(run(r.say('A line.')),
                          "a request that never left must not be waited for")
        self.assertEqual(r.status()['pending'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2, exit=False)
    sys.exit(0)
