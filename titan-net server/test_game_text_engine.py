#!/usr/bin/env python3
"""
The text engine: a game turn taken over generateContent, not over Live.

Run it directly. No API key, no network, no audio device: the model is a
scripted stand-in speaking the SDK's own shapes, which is the only way to
test the answers a real model gets WRONG - a model this key has not got, a
turn that is nothing but the model thinking out loud, two players typing at
the same moment, a conversation trimmed across a tool call.
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gemini_game_worker as gw                       # noqa: E402
from google.genai import types as gt                  # noqa: E402
from test_interactive_games import GameTestCase       # noqa: E402


# ---------------------------------------------------------------------------
# The stand-in model
# ---------------------------------------------------------------------------

class FakeUsage:
    def __init__(self, total, prompt=None, cached=0, answer=None):
        self.total_token_count = total
        self.prompt_token_count = total if prompt is None else prompt
        self.cached_content_token_count = cached
        self.candidates_token_count = (
            max(total - (total if prompt is None else prompt), 0)
            if answer is None else answer)


class FakeCandidate:
    def __init__(self, content):
        self.content = content


class FakeAnswer:
    """One generate_content answer, in the shape the SDK returns."""

    def __init__(self, text=None, calls=(), tokens=100, usage=None):
        self._text = text
        parts = []
        self.function_calls = list(calls)
        for call in self.function_calls:
            parts.append(gt.Part(function_call=gt.FunctionCall(
                name=call.name, args=call.args)))
        if text:
            parts.append(gt.Part(text=text))
        self.candidates = [FakeCandidate(gt.Content(role='model', parts=parts))]
        self.usage_metadata = usage or FakeUsage(tokens)

    @property
    def text(self):
        return self._text


class FakeCall:
    def __init__(self, name, **args):
        self.name = name
        self.args = args


class FakeAsyncModels:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    async def generate_content(self, *, model, contents, config):
        self.calls.append({'model': model, 'contents': list(contents),
                           'config': config})
        if not self.script:
            return FakeAnswer(text='And so it goes on.')
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeAio:
    def __init__(self, models):
        self.models = models


class FakeModelEntry:
    def __init__(self, name, actions):
        self.name = name
        self.supported_actions = actions


class FakeClient:
    """Answers the two things the text engine asks of a client."""

    def __init__(self, script=(), listed=None):
        self.aio = FakeAio(FakeAsyncModels(script))
        self._listed = listed if listed is not None else [
            FakeModelEntry('models/gemini-3.7-flash', ['generateContent']),
            FakeModelEntry('models/gemini-2.5-flash', ['generateContent']),
            FakeModelEntry('models/gemini-2.5-flash-image', ['generateContent']),
            FakeModelEntry('models/gemini-2.5-flash-native-audio-latest',
                           ['bidiGenerateContent']),
        ]
        self.models = self

    def list(self):
        return list(self._listed)


# ---------------------------------------------------------------------------

class TextEngineTestCase(GameTestCase):

    def make_text_worker(self, script=(), listed=None, rules=None):
        game_id = self.make_game(
            rules_text=rules or 'The table is a hundred fields long.')
        session_id = self.make_session(game_id, players=[self.alice_id])
        worker = self.make_worker(session_id, game_id)
        worker._game = self.db.get_game(game_id, include_api_key=True)
        worker._client = FakeClient(script, listed=listed)
        worker._tools = [{'function_declarations': gw.TOOL_SCHEMAS}]
        worker._system_prompt = gw.build_system_prompt(worker._game)
        worker._text_models = ['gemini-3.7-flash']
        return worker

    @property
    def model(self):
        return 'gemini-3.7-flash'


class TestPickingAModel(TextEngineTestCase):

    def test_the_best_candidate_this_key_lists_comes_first(self):
        worker = self.make_text_worker()
        picked = self.run_async(worker._pick_text_models())
        self.assertEqual(picked[0], 'gemini-3.7-flash')

    def test_a_model_for_pictures_is_never_picked(self):
        worker = self.make_text_worker()
        picked = self.run_async(worker._pick_text_models())
        self.assertNotIn('gemini-2.5-flash-image', picked)

    def test_a_voice_model_is_not_a_text_model(self):
        worker = self.make_text_worker()
        picked = self.run_async(worker._pick_text_models())
        self.assertNotIn('gemini-2.5-flash-native-audio-latest', picked)

    def test_a_key_with_nothing_but_voice_models_takes_the_live_path(self):
        worker = self.make_text_worker(listed=[
            FakeModelEntry('models/gemini-2.5-flash-native-audio-latest',
                           ['bidiGenerateContent'])])
        self.assertEqual(self.run_async(worker._pick_text_models()), [])

    def test_a_listing_that_fails_still_leaves_the_candidates(self):
        worker = self.make_text_worker()

        def _boom():
            raise RuntimeError('no network')
        worker._client.list = _boom
        picked = self.run_async(worker._pick_text_models())
        self.assertEqual(list(picked), list(worker.TEXT_MODEL_CANDIDATES))

    def test_the_game_may_name_its_own_model(self):
        worker = self.make_text_worker()
        worker._game = dict(worker._game or {})
        worker._game['model_name'] = 'gemini-2.5-flash'
        picked = self.run_async(worker._pick_text_models())
        self.assertEqual(picked[0], 'gemini-2.5-flash')

    def test_a_named_model_this_key_has_not_got_is_ignored(self):
        worker = self.make_text_worker()
        worker._game = dict(worker._game or {})
        worker._game['model_name'] = 'gemini-9-imaginary'
        picked = self.run_async(worker._pick_text_models())
        self.assertEqual(picked[0], 'gemini-3.7-flash')

    def test_an_sdk_with_no_async_generate_content_stays_on_live(self):
        worker = self.make_text_worker()
        worker._client.aio = None
        self.assertEqual(self.run_async(worker._pick_text_models()), [])

    def test_the_switch_turns_the_whole_engine_off(self):
        worker = self.make_text_worker()
        old = gw.TEXT_ENGINE_ENABLED
        gw.TEXT_ENGINE_ENABLED = False
        try:
            self.assertEqual(self.run_async(worker._pick_text_models()), [])
        finally:
            gw.TEXT_ENGINE_ENABLED = old


class TestATurn(TextEngineTestCase):

    def test_a_plain_turn_is_narrated_once(self):
        worker = self.make_text_worker(
            script=[FakeAnswer(text='The stone is cold under your boot.')])
        self.run_async(worker._take_text_turn('[alice] I step onto the table'))
        said = self.messages(worker, 'game_ai_text')
        self.assertEqual(len(said), 1)
        self.assertEqual(said[0]['text'], 'The stone is cold under your boot.')
        self.assertEqual(said[0]['actor'], 'gm')

    def test_a_tool_is_run_and_its_answer_goes_back(self):
        worker = self.make_text_worker(script=[
            FakeAnswer(calls=[FakeCall('roll_dice', notation='1d6')]),
            FakeAnswer(text='The die shows what it shows.'),
        ])
        self.run_async(worker._take_text_turn('[alice] I roll'))
        second = worker._client.aio.models.calls[1]['contents']
        # The model's own turn, then the answer to its call.
        answer = second[-1]
        self.assertEqual(answer.role, 'user')
        self.assertIsNotNone(answer.parts[0].function_response)
        self.assertEqual(answer.parts[0].function_response.name, 'roll_dice')
        self.assertEqual(len(self.messages(worker, 'game_ai_text')), 1)

    def test_the_model_s_own_turn_is_kept_verbatim(self):
        """Gemini 3 signs its function calls, and the signature has to go
        back with the answer - so the model's content is appended as it
        came, never rebuilt."""
        worker = self.make_text_worker(script=[
            FakeAnswer(calls=[FakeCall('roll_dice', notation='1d6')]),
            FakeAnswer(text='Done.'),
        ])
        self.run_async(worker._take_text_turn('[alice] I roll'))
        sent = worker._client.aio.models.calls[1]['contents']
        self.assertEqual(sent[-2].role, 'model')
        self.assertIsNotNone(sent[-2].parts[0].function_call)

    def test_the_whole_ruleset_rides_on_every_turn(self):
        worker = self.make_text_worker(
            rules='The table is a hundred fields long and unlit.',
            script=[FakeAnswer(text='Dark.')])
        self.run_async(worker._take_text_turn('[alice] look'))
        config = worker._client.aio.models.calls[0]['config']
        self.assertIn('hundred fields long', config.system_instruction)

    def test_thinking_out_loud_is_not_narration(self):
        worker = self.make_text_worker(script=[FakeAnswer(text='Let me check')])
        self.run_async(worker._take_text_turn('[alice] hello'))
        self.assertEqual(self.messages(worker, 'game_ai_text'), [])

    def test_a_turn_that_says_nothing_says_nothing(self):
        worker = self.make_text_worker(script=[FakeAnswer(text=None)])
        self.run_async(worker._take_text_turn('[alice] hello'))
        self.assertEqual(self.messages(worker, 'game_ai_text'), [])

    def test_what_the_turn_cost_is_counted(self):
        worker = self.make_text_worker(
            script=[FakeAnswer(text='A line.', tokens=1234)])
        self.run_async(worker._take_text_turn('[alice] hello'))
        session = self.db.get_game_session(worker.session_id)
        self.assertGreaterEqual(int(session.get('tokens_used') or 0), 1234)

    def test_a_tool_loop_cannot_hold_the_table_for_ever(self):
        worker = self.make_text_worker(script=[
            FakeAnswer(calls=[FakeCall('roll_dice', notation='1d6')])
            for _ in range(40)
        ])
        self.run_async(worker._take_text_turn('[alice] I roll'))
        self.assertLessEqual(len(worker._client.aio.models.calls),
                             worker.MAX_TOOL_ROUNDS)

    def test_the_players_words_are_recorded_for_the_archive(self):
        worker = self.make_text_worker(script=[FakeAnswer(text='A line.')])
        self.run_async(worker._take_text_turn('[alice] I step forward'))
        roles = [h['role'] for h in worker._history]
        self.assertEqual(roles, ['user', 'model'])


class TestAModelThisKeyHasNotGot(TextEngineTestCase):

    def test_a_missing_model_is_rotated_past(self):
        worker = self.make_text_worker(script=[
            RuntimeError('404 models/gemini-3.7-flash is not found'),
            FakeAnswer(text='The next one answered.'),
        ])
        worker._text_models = ['gemini-3.7-flash', 'gemini-2.5-flash']
        self.run_async(worker._take_text_turn('[alice] hello'))
        self.assertEqual(worker._text_models[0], 'gemini-2.5-flash')
        self.assertEqual(len(self.messages(worker, 'game_ai_text')), 1)

    def test_an_ordinary_failure_is_not_rotated_past(self):
        """A quota or a network blip is answered the same way by the next
        model, so rotating for it would only spend the key twice."""
        worker = self.make_text_worker(script=[
            RuntimeError('429 RESOURCE_EXHAUSTED'),
        ])
        worker._text_models = ['gemini-3.7-flash', 'gemini-2.5-flash']
        self.run_async(worker._take_text_turn('[alice] hello'))
        self.assertEqual(worker._text_models[0], 'gemini-3.7-flash')
        said = self.messages(worker, 'game_ai_text')
        self.assertTrue(said and 'AI error' in said[0]['text'])

    def test_a_turn_that_never_answers_is_not_waited_out_for_ever(self):
        worker = self.make_text_worker()
        worker.TEXT_TURN_TIMEOUT_S = 0.05

        async def _never(**kwargs):
            await asyncio.sleep(5)
        worker._client.aio.models.generate_content = _never
        self.run_async(worker._take_text_turn('[alice] hello'))
        said = self.messages(worker, 'game_ai_text')
        self.assertTrue(said and 'did not answer in time' in said[0]['text'])


class TestTheConversation(TextEngineTestCase):

    def _content(self, role, text=None, function_response=False):
        if function_response:
            part = gt.Part.from_function_response(name='roll_dice',
                                                  response={'output': {}})
        else:
            part = gt.Part(text=text or 'x')
        return gt.Content(role=role, parts=[part])

    def test_trimming_never_orphans_a_tool_answer(self):
        """A function response with no call in front of it is refused by
        the API outright, so a cut has to land on a player's own words."""
        worker = self.make_text_worker()
        worker.MAX_HISTORY = 2      # limit becomes 8 entries
        for _ in range(6):
            worker._chat.append(self._content('user', 'I roll'))
            worker._chat.append(self._content('model'))
            worker._chat.append(self._content('user', function_response=True))
        worker._trim_chat()
        self.assertTrue(worker._is_turn_start(worker._chat[0]))
        self.assertLessEqual(len(worker._chat), 8 + 2)

    def test_a_short_conversation_is_left_alone(self):
        worker = self.make_text_worker()
        worker._chat.append(self._content('user', 'hello'))
        worker._trim_chat()
        self.assertEqual(len(worker._chat), 1)

    def test_two_players_at_once_do_not_interleave(self):
        """Two turns building on one half-written conversation is how a
        function response ends up with no call in front of it."""
        worker = self.make_text_worker(script=[
            FakeAnswer(calls=[FakeCall('roll_dice', notation='1d6')]),
            FakeAnswer(text='Alice rolls.'),
            FakeAnswer(text='Bob waits.'),
        ])

        async def _both():
            await asyncio.gather(
                worker._take_text_turn('[alice] I roll'),
                worker._take_text_turn('[bob] I wait'),
            )
        self.run_async(_both())
        for call in worker._client.aio.models.calls:
            previous = None
            for content in call['contents']:
                if content.parts and content.parts[0].function_response:
                    self.assertIsNotNone(previous)
                    self.assertEqual(previous.role, 'model')
                previous = content
        self.assertEqual(len(self.messages(worker, 'game_ai_text')), 2)


class TestTheGameOpeningItself(TextEngineTestCase):

    def test_nobody_has_to_say_hello_first(self):
        worker = self.make_text_worker(
            script=[FakeAnswer(text='The torchlight gutters.')])
        worker.OPENING_DELAY_S = 0.01
        self.run_async(worker._open_the_game())
        said = self.messages(worker, 'game_ai_text')
        self.assertEqual(len(said), 1)
        self.assertEqual(said[0]['text'], 'The torchlight gutters.')

    def test_the_opening_instruction_is_not_a_player_turn(self):
        """It is the server's own words, so it must not end up in the
        archive as something a player said."""
        worker = self.make_text_worker(script=[FakeAnswer(text='Dark stone.')])
        worker.OPENING_DELAY_S = 0.01
        self.run_async(worker._open_the_game())
        self.assertEqual([h['role'] for h in worker._history], ['model'])

    def test_a_game_somebody_has_already_spoken_to_does_not_reopen(self):
        worker = self.make_text_worker(script=[FakeAnswer(text='Should not.')])
        worker.OPENING_DELAY_S = 0.01
        worker._history.append({'role': 'user', 'text': '[alice] hello'})
        self.run_async(worker._open_the_game())
        self.assertEqual(self.messages(worker, 'game_ai_text'), [])

    def test_a_session_being_torn_down_does_not_open_a_game(self):
        worker = self.make_text_worker(script=[FakeAnswer(text='Should not.')])
        worker.OPENING_DELAY_S = 0.01

        async def _go():
            worker._stop_event.set()
            await worker._open_the_game()
        self.run_async(_go())
        self.assertEqual(self.messages(worker, 'game_ai_text'), [])


class TestTheTurnAlwaysSaysSomething(TextEngineTestCase):

    def test_a_turn_that_only_calls_tools_is_made_to_narrate(self):
        """Setting a board game up is thirty calls. Cut off at the ceiling
        with nothing said, the table hears silence and cannot tell the
        game from a crash - so the last round is asked with no tools at
        all and has to answer in words."""
        worker = self.make_text_worker(script=[
            FakeAnswer(calls=[FakeCall('roll_dice', notation='1d6')])
            for _ in range(3)
        ] + [FakeAnswer(text='The die falls off the table.')])
        worker.MAX_TOOL_ROUNDS = 4
        self.run_async(worker._take_text_turn('[alice] I roll'))
        said = self.messages(worker, 'game_ai_text')
        self.assertEqual(len(said), 1)
        self.assertEqual(said[0]['text'], 'The die falls off the table.')

    def test_the_last_round_is_asked_without_tools(self):
        worker = self.make_text_worker(script=[
            FakeAnswer(calls=[FakeCall('roll_dice', notation='1d6')]),
            FakeAnswer(text='Done.'),
        ])
        worker.MAX_TOOL_ROUNDS = 2
        self.run_async(worker._take_text_turn('[alice] I roll'))
        calls = worker._client.aio.models.calls
        self.assertIsNotNone(calls[0]['config'].tools)
        self.assertIsNone(calls[-1]['config'].tools)

    def test_a_turn_that_runs_long_stops_asking_for_tools(self):
        worker = self.make_text_worker(script=[
            FakeAnswer(text='Enough.'),
        ])
        worker.TURN_BUDGET_S = -1.0      # already over budget
        self.run_async(worker._take_text_turn('[alice] I roll'))
        self.assertIsNone(worker._client.aio.models.calls[0]['config'].tools)
        self.assertEqual(len(self.messages(worker, 'game_ai_text')), 1)


class TestWhatATurnIsCharged(TextEngineTestCase):

    def test_a_cached_ruleset_is_not_charged_again(self):
        """Every request on this path re-presents the whole system prompt,
        so charging total_token_count charges the creator's rules once per
        REQUEST. Measured playing Czarny Stol: two turns of an 11 KB
        ruleset 'spent' 200 475 tokens and the session ended itself."""
        worker = self.make_text_worker(script=[FakeAnswer(
            text='A line.',
            usage=FakeUsage(total=30000, prompt=29000, cached=28000,
                            answer=1000))])
        self.run_async(worker._take_text_turn('[alice] hello'))
        used = int(self.db.get_game_session(
            worker.session_id).get('tokens_used') or 0)
        self.assertEqual(used, 2000)      # (29000 - 28000) + 1000

    def test_a_turn_with_no_cache_is_charged_in_full(self):
        worker = self.make_text_worker(script=[FakeAnswer(
            text='A line.',
            usage=FakeUsage(total=5000, prompt=4000, cached=0, answer=1000))])
        self.run_async(worker._take_text_turn('[alice] hello'))
        used = int(self.db.get_game_session(
            worker.session_id).get('tokens_used') or 0)
        self.assertEqual(used, 5000)


class TestWhoIsAtTheTable(TextEngineTestCase):

    def test_the_opening_says_who_is_playing(self):
        """Without the roster the model invents a character for the player
        it was never introduced to - measured: it set up a full sheet for
        a 'Gracz' while the real player had none."""
        worker = self.make_text_worker(script=[FakeAnswer(text='Dark stone.')])
        worker.OPENING_DELAY_S = 0.01
        self.run_async(worker._open_the_game())
        sent = worker._client.aio.models.calls[0]['contents'][0]
        opening = sent.parts[0].text
        self.assertIn('alice', opening)

    def test_an_empty_table_is_not_opened(self):
        game_id = self.make_game()
        session_id = self.db.create_game_session(
            game_id, host_id=self.alice_id)['session_id']
        worker = self.make_worker(session_id, game_id)
        worker._client = FakeClient([FakeAnswer(text='Should not.')])
        worker._tools = []
        worker._system_prompt = 'x'
        worker._text_models = ['gemini-3.7-flash']
        worker.OPENING_DELAY_S = 0.01
        # The host is on the roster, so empty means really empty.
        self.db.remove_session_player(session_id, self.alice_id)
        self.run_async(worker._open_the_game())
        self.assertEqual(self.messages(worker, 'game_ai_text'), [])


class TestVoice(TextEngineTestCase):

    def chunk(self, worker, user_id, username, seconds=0.5):
        import base64
        pcm = b'\x00\x01' * int(worker.VOICE_SAMPLE_RATE * seconds)
        worker._buffer_voice({
            'user_id': user_id, 'username': username,
            'audio_b64': base64.b64encode(pcm).decode('ascii'),
        })

    def test_a_gap_is_what_ends_a_spoken_turn(self):
        worker = self.make_text_worker(script=[FakeAnswer(text='Heard you.')])
        worker.VOICE_GAP_S = 0.01
        self.chunk(worker, self.alice_id, 'alice')

        async def _go():
            task = asyncio.ensure_future(worker._voice_watch())
            await asyncio.sleep(0.9)
            task.cancel()
            try:
                await task
            except Exception:
                pass
        self.run_async(_go())
        self.assertEqual(len(self.messages(worker, 'game_ai_text')), 1)
        sent = worker._client.aio.models.calls[0]['contents'][-1]
        kinds = [p.inline_data.mime_type for p in sent.parts if p.inline_data]
        self.assertEqual(kinds, ['audio/wav'])

    def test_a_cough_is_not_a_turn(self):
        worker = self.make_text_worker(script=[FakeAnswer(text='Should not.')])
        worker.VOICE_GAP_S = 0.01
        self.chunk(worker, self.alice_id, 'alice', seconds=0.01)

        async def _go():
            task = asyncio.ensure_future(worker._voice_watch())
            await asyncio.sleep(0.9)
            task.cancel()
            try:
                await task
            except Exception:
                pass
        self.run_async(_go())
        self.assertEqual(self.messages(worker, 'game_ai_text'), [])

    def test_a_player_who_will_not_stop_talking_is_capped(self):
        worker = self.make_text_worker()
        for _ in range(200):
            self.chunk(worker, self.alice_id, 'alice', seconds=1.0)
        buffered = worker._voice[self.alice_id]['bytes']
        cap = worker.VOICE_MAX_SECONDS * worker.VOICE_SAMPLE_RATE * 2
        self.assertLessEqual(buffered, cap + worker.VOICE_SAMPLE_RATE * 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
