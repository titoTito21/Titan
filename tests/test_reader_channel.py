# -*- coding: utf-8 -*-
"""Whichever reader is listening, and how much of Titan's meaning survives.

Run it directly (`python tests/test_reader_channel.py`) - `tests/` has no
`__init__.py`.

Nothing here speaks, opens a window, plays a sound or reaches the bus: the
reader is a stand-in that records what it was handed, which is the only way
to test the thing that actually went wrong before - not what Titan said, but
what it decided NOT to say.  `announce_view_switched` stayed silent for every
reader but Titan's own, and a test that only checks the wording of what IS
said would have passed on that for as long as it stood.
"""

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.accessibility import messages                           # noqa: E402
from src.accessibility import reader_channel                     # noqa: E402


# --------------------------------------------------------------------------- #
# Stand-ins
# --------------------------------------------------------------------------- #
class Recorder(reader_channel.Channel):
    """A reader that takes exactly what it is told it takes, and remembers."""

    name = 'recorder'

    def __init__(self, **capabilities):
        self._capabilities = dict(capabilities)
        self.said = []

    def can(self, what):
        return bool(self._capabilities.get(what))

    def capabilities(self):
        return dict(self._capabilities)

    def say(self, message):
        self.said.append(message)
        return True


class FakePeer:
    """A reader add-on on the bus, with a spy where the pipe would be."""

    def __init__(self, addon_id='nvda', capabilities=None, answer=True):
        self.addon_id = addon_id
        self.alive = True
        self.joined_at = 1000.0
        self.calls = []
        self._capabilities = capabilities if capabilities is not None else {
            'announce': True, 'position': True, 'pitch': True, 'rate': True,
            'volume': True, 'braille': True, 'queue': True,
            'replaces_focus': True,
        }
        self._answer = answer

    def invoke(self, action, args, timeout=None):
        self.calls.append((action, args, timeout))
        if action == 'capabilities':
            return True, dict(self._capabilities)
        return bool(self._answer), {'spoken': True}


class Swap:
    """Put a channel in front of Titan for the length of a test."""

    def __init__(self, test, channel):
        self.test = test
        self.channel = channel

    def __enter__(self):
        self.previous = reader_channel.channel
        reader_channel.channel = lambda: self.channel
        return self.channel

    def __exit__(self, *_):
        reader_channel.channel = self.previous
        return False


def in_place(name, index=None, count=None, role=None):
    """The sentence Titan would say, in whatever language Titan is in.

    Spelling the expected string out in English would make these tests pass
    only on an English Titan - and the wording is the point, so it is built
    from the same msgids the announcement is built from.
    """
    head = name
    if index is not None and count:
        head = messages._('{}, {} of {}').format(name, index, count)
    return head if role is None else '{}, {}'.format(head, role)


def quiet(test):
    """No sound, from a suite that must make none."""
    original = messages.play_sound
    messages.play_sound = lambda *_a, **_k: None
    test.addCleanup(lambda: setattr(messages, 'play_sound', original))


# --------------------------------------------------------------------------- #
class WhatEachChannelReallyTakes(unittest.TestCase):
    """A capability that lies is worse than one that is absent."""

    def test_titan_access_claims_only_what_announce_carries(self):
        channel = reader_channel.TitanAccessChannel()
        for carried in ('text', 'pitch', 'queue', 'replaces_focus'):
            self.assertTrue(channel.can(carried), carried)

    def test_titan_access_does_not_claim_a_role_it_folds_into_the_sentence(self):
        # `host_bridge.announce` takes text, interrupt and pitch. Claiming a
        # role as a FIELD would make the caller hand one over believing the
        # reader would word it in the user's own verbosity settings.
        channel = reader_channel.TitanAccessChannel()
        for absent in ('role', 'states', 'index', 'position', 'braille'):
            self.assertFalse(channel.can(absent), absent)

    def test_a_plain_reader_takes_the_words_and_nothing_else(self):
        channel = reader_channel.PlainChannel()
        self.assertTrue(channel.can('text'))
        for absent in ('position', 'pitch', 'role', 'index', 'replaces_focus'):
            self.assertFalse(channel.can(absent), absent)

    def test_a_channel_with_nobody_behind_it_takes_nothing(self):
        channel = reader_channel.Channel()
        self.assertFalse(channel.can('text'))
        self.assertFalse(channel.say(reader_channel.Message('anything')))


class WhatIsFoldedAwayAndWhatSurvives(unittest.TestCase):
    """Anything a reader cannot take apart comes back inside the sentence."""

    def test_the_sentence_is_titans_own_wording(self):
        message = reader_channel.Message('Applications', role='tab',
                                         index=1, count=4)
        self.assertEqual(message.sentence(),
                         in_place('Applications', 1, 4, 'tab'))

    def test_a_name_on_its_own_is_the_whole_sentence(self):
        self.assertEqual(reader_channel.Message('Dock').sentence(), 'Dock')

    def test_a_place_in_a_list_with_no_count_is_not_said(self):
        message = reader_channel.Message('Dock', index=2, count=None)
        self.assertEqual(message.sentence(), 'Dock')

    def test_states_follow_the_role(self):
        message = reader_channel.Message('Show hidden icons', role='button',
                                         states=('pressed',))
        self.assertEqual(message.sentence(), 'Show hidden icons, button, pressed')

    def test_a_reader_that_cannot_take_a_role_apart_hears_it_anyway(self):
        channel = Recorder(position=True, pitch=True)
        payload = reader_channel.Message('Applications', role='tab',
                                         index=1, count=4).for_addon(channel)
        self.assertEqual(payload['text'],
                         in_place('Applications', 1, 4, 'tab'))
        self.assertNotIn('role', payload)
        self.assertNotIn('index', payload)

    def test_a_reader_that_can_gets_the_pieces(self):
        channel = Recorder(role=True, index=True)
        payload = reader_channel.Message('Applications', role='tab',
                                         index=1, count=4).for_addon(channel)
        self.assertEqual(payload['text'], 'Applications')
        self.assertEqual(payload['role'], 'tab')
        self.assertEqual((payload['index'], payload['count']), (1, 4))

    def test_a_position_is_not_sent_to_a_reader_that_cannot_pan(self):
        payload = reader_channel.Message('left', position=-1.0).for_addon(
            Recorder())
        self.assertNotIn('position', payload)

    def test_a_position_is_sent_to_one_that_can_only_mark_it(self):
        # A synth that cannot be panned can still be given a tone where the
        # thing is, so the position is worth sending.
        payload = reader_channel.Message('left', position=-1.0).for_addon(
            Recorder(position_marker=True))
        self.assertEqual(payload['position'], -1.0)

    def test_braille_travels_only_when_it_is_wanted(self):
        message = reader_channel.Message('12 items', braille='12')
        self.assertNotIn('braille', message.for_addon(Recorder()))
        self.assertEqual(message.for_addon(Recorder(braille=True))['braille'],
                         '12')

    def test_replaces_focus_is_never_sent_to_a_reader_that_cannot_suppress(self):
        message = reader_channel.Message('Dock', replaces_focus=True)
        self.assertNotIn('replaces_focus', message.for_addon(Recorder()))
        self.assertTrue(
            message.for_addon(Recorder(replaces_focus=True))['replaces_focus'])


class ChoosingTheReader(unittest.TestCase):
    """Titan Access, then a reader add-on, then whatever text can be sent."""

    def setUp(self):
        self._peer = None
        self._titan_access = False

        class Bus:
            @staticmethod
            def get_peer(addon_id, _self=self):
                if _self._peer is not None and _self._peer.addon_id == addon_id:
                    return _self._peer
                return None

            @staticmethod
            def invoke(addon_id, action, args=None, timeout=None, _self=self):
                return _self._peer.invoke(action, args, timeout)

        self.bus = Bus
        module = type(sys)('src.titan_core.actions.bus')
        module.get_peer = Bus.get_peer
        module.invoke = Bus.invoke
        self._saved = sys.modules.get('src.titan_core.actions.bus')
        sys.modules['src.titan_core.actions.bus'] = module
        self._saved_titan = reader_channel._titan_access_active
        reader_channel._titan_access_active = lambda: self._titan_access
        reader_channel._cache.update({'peer': None, 'joined': 0.0,
                                      'capabilities': {}, 'asked': 0.0})

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop('src.titan_core.actions.bus', None)
        else:
            sys.modules['src.titan_core.actions.bus'] = self._saved
        reader_channel._titan_access_active = self._saved_titan

    def test_titan_access_wins_even_when_an_addon_is_on_the_bus(self):
        self._titan_access = True
        self._peer = FakePeer()
        self.assertEqual(reader_channel.channel().name, 'titan_access')

    def test_a_reader_addon_is_used_when_titan_access_is_not_running(self):
        self._peer = FakePeer()
        channel = reader_channel.channel()
        self.assertEqual(channel.name, 'addon')
        self.assertTrue(channel.can('position'))

    def test_a_reader_that_will_not_announce_is_not_the_reader(self):
        """Switched off in the add-on must mean NVDA's own behaviour back.

        The reader's user turned Titan's announcements off inside it, and
        the add-on used to claim it could take one anyway and then drop it
        with a reason nobody reads. That is worse than not having the
        add-on at all: `announce_view_switched` and `announce_shell_group`
        ask `replaces_focus` FIRST and stay quiet when the answer is no, so
        those sentences were lost in both directions at once.
        """
        self._peer = FakePeer(capabilities={'announce': False,
                                            'replaces_focus': True})
        self.assertNotEqual(reader_channel.channel().name, 'addon')

    def test_a_reader_older_than_the_key_is_still_the_reader(self):
        """Absence is not a refusal: an add-on written before `announce`
        existed answers everything it can do and never mentions it."""
        self._peer = FakePeer(capabilities={'position': True})
        self.assertEqual(reader_channel.channel().name, 'addon')

    def test_a_channel_told_no_says_nothing_even_if_it_is_asked(self):
        channel = reader_channel.AddonChannel('nvda', {'announce': False})
        self._peer = FakePeer()
        self.assertFalse(channel.say(reader_channel.Message('x')))
        self.assertEqual(self._peer.calls, [])

    def test_a_peer_that_has_gone_is_not_the_reader(self):
        self._peer = FakePeer()
        self._peer.alive = False
        self.assertNotEqual(reader_channel.channel().name, 'addon')

    def test_the_reader_is_told_which_process_titan_is_once(self):
        self._peer = FakePeer()
        reader_channel.channel()
        reader_channel.channel()
        attaches = [call for call in self._peer.calls if call[0] == 'attach']
        self.assertEqual(len(attaches), 1)
        self.assertEqual(attaches[0][1]['pid'], os.getpid())

    def test_what_the_reader_takes_is_not_asked_once_per_sentence(self):
        self._peer = FakePeer()
        for _ in range(5):
            reader_channel.channel()
        asked = [call for call in self._peer.calls if call[0] == 'capabilities']
        self.assertEqual(len(asked), 1)

    def test_an_answer_of_nothing_is_not_kept_like_a_real_one(self):
        """A reader that was slow for one call must not cost twenty seconds.

        Measured live: one slow COM call on the reader's side made Titan
        cache an EMPTY capability set, and for the next twenty seconds it
        sent flat text with no position, no tones and nothing marked as
        replacing the reader's own report - so NVDA read every control and
        the add-on read it again on top.
        """
        self._peer = FakePeer(capabilities={})
        for _ in range(3):
            reader_channel.channel()
        asked = [c for c in self._peer.calls if c[0] == 'capabilities']
        self.assertEqual(len(asked), 3, 'nothing is worth asking again')

    def test_a_real_answer_is_kept(self):
        self._peer = FakePeer()
        for _ in range(4):
            reader_channel.channel()
        asked = [c for c in self._peer.calls if c[0] == 'capabilities']
        self.assertEqual(len(asked), 1)

    def test_titan_never_waits_on_a_reader(self):
        self._peer = FakePeer()
        channel = reader_channel.channel()
        channel.say(reader_channel.Message('anything'))
        for _action, _args, timeout in self._peer.calls:
            self.assertIsNotNone(timeout)
            self.assertLessEqual(timeout, reader_channel.CALL_TIMEOUT)

    def test_a_reader_whose_addon_is_not_the_one_we_know_is_not_used(self):
        self._peer = FakePeer(addon_id='some_other_program')
        self.assertNotEqual(reader_channel.channel().name, 'addon')


class TheAnnouncementsThatUsedToBeSilent(unittest.TestCase):
    """The whole reason the channel exists."""

    def setUp(self):
        quiet(self)

    def test_the_tab_bar_view_is_said_to_a_reader_that_can_suppress_its_own(self):
        recorder = Recorder(replaces_focus=True)
        with Swap(self, recorder):
            self.assertTrue(messages.announce_view_switched('Applications', 0, 4))
        said = recorder.said[0]
        self.assertEqual(said.sentence(),
                         in_place('Applications', 1, 4, messages._('tab')))
        self.assertTrue(said.replaces_focus)

    def test_it_stays_silent_where_it_would_be_the_row_read_twice(self):
        recorder = Recorder(text=True)          # a plain accessible_output3
        with Swap(self, recorder):
            self.assertFalse(messages.announce_view_switched('Applications', 0, 4))
        self.assertEqual(recorder.said, [])

    def test_a_tab_bar_with_one_view_still_says_which_view(self):
        recorder = Recorder(replaces_focus=True)
        with Swap(self, recorder):
            messages.announce_view_switched('Applications', 0, 0)
        self.assertEqual(recorder.said[0].sentence(),
                         in_place('Applications', role=messages._('tab')))

    def test_the_tab_bar_still_says_it_is_the_tab_bar(self):
        """Pinned, because breaking it is exactly what happened once.

        Everything else about the tab bar can change; that arriving on it
        says so must not.
        """
        recorder = Recorder(replaces_focus=True)
        with Swap(self, recorder):
            messages.announce_tab_bar()
        self.assertEqual(len(recorder.said), 1)
        self.assertIn(messages._("Tab bar"), recorder.said[0].sentence())

    def test_arriving_on_the_tab_bar_says_which_tab(self):
        recorder = Recorder(replaces_focus=True)
        with Swap(self, recorder):
            messages.announce_tab_bar('Applications', 1, 4)
        line = recorder.said[0].sentence()
        self.assertIn(messages._("Tab bar"), line)
        self.assertIn('Applications', line)
        self.assertIn(messages._("tab"), line)

    def test_and_says_it_in_three_tones(self):
        # The place at the neutral tone, what it is lower, which one higher
        # - Titan Access's own shape.
        recorder = Recorder(replaces_focus=True)
        with Swap(self, recorder):
            messages.announce_tab_bar('Applications', 1, 4)
        parts = recorder.said[0].segments()
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0][1], reader_channel.NAME_PITCH)
        self.assertEqual(parts[1][1], reader_channel.ROLE_PITCH)
        self.assertEqual(parts[2][1], reader_channel.STATE_PITCH)
        self.assertIn('Applications', parts[2][0])

    def test_a_caller_that_does_not_know_its_tabs_is_unchanged(self):
        recorder = Recorder(replaces_focus=True)
        with Swap(self, recorder):
            messages.announce_tab_bar()
        self.assertEqual(len(recorder.said[0].segments()), 1)

    def test_it_replaces_the_readers_own_read_of_the_row(self):
        recorder = Recorder(replaces_focus=True)
        with Swap(self, recorder):
            messages.announce_tab_bar('Applications', 1, 4)
        self.assertTrue(recorder.said[0].replaces_focus)

    def test_written_out_parts_survive_to_a_reader_that_takes_them(self):
        message = reader_channel.Message(
            'x', parts=[('Tab bar', 0), ('tab', -4), ('Applications', 4)])
        payload = message.for_addon(Recorder(segments=True))
        self.assertEqual(payload['segments'],
                         [['Tab bar', 0], ['tab', -4], ['Applications', 4]])
        self.assertEqual(payload['text'], 'Tab bar, tab, Applications')

    def test_a_shell_group_reaches_every_reader(self):
        for capabilities in ({'text': True}, {'replaces_focus': True}):
            recorder = Recorder(**capabilities)
            with Swap(self, recorder):
                self.assertTrue(messages.announce_shell_group('Dock'))
            self.assertEqual(recorder.said[0].text, 'Dock')

    def test_a_group_says_where_on_the_bar_it_is(self):
        """The field existed from the start and no caller ever filled it in.

        That was the whole of "there is no positioned speech": not a panner
        that did not work, but a panner that was never given a place to put
        the voice.
        """
        recorder = Recorder(replaces_focus=True, position=True)
        with Swap(self, recorder):
            messages.announce_shell_group('System tray', 0.9)
        self.assertAlmostEqual(recorder.said[0].position, 0.9)

    def test_the_position_reaches_a_reader_that_can_place_its_voice(self):
        recorder = Recorder(replaces_focus=True, position=True)
        payload = reader_channel.Message('Dock', position=-1.0,
                                         replaces_focus=True).for_addon(recorder)
        self.assertEqual(payload['position'], -1.0)

    def test_a_group_in_the_middle_is_still_a_position(self):
        # Dead centre is a real answer, not a missing one: it is what the
        # reader puts the voice back to.
        recorder = Recorder(replaces_focus=True, position=True)
        with Swap(self, recorder):
            messages.announce_shell_group('Dock')
        self.assertEqual(recorder.said[0].position, 0.0)

    def test_a_group_with_no_name_says_nothing(self):
        recorder = Recorder(replaces_focus=True)
        with Swap(self, recorder):
            self.assertFalse(messages.announce_shell_group(''))
        self.assertEqual(recorder.said, [])

    def test_where_the_file_browser_went_reaches_every_reader(self):
        recorder = Recorder(text=True)
        with Swap(self, recorder):
            self.assertTrue(messages.announce_shell_location('Documents', 12))
        self.assertIn('Documents', recorder.said[0].text)
        self.assertIn('12', recorder.said[0].text)

    def test_a_dragged_card_is_announced_in_two_tones(self):
        recorder = Recorder(replaces_focus=True, pitch=True)
        with Swap(self, recorder):
            self.assertTrue(messages.announce_drag_move('Applications', 2))
        # ONE utterance: two announcements about one arrow key is how one
        # of them goes missing.
        self.assertEqual(len(recorder.said), 1)
        parts = recorder.said[0].segments()
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0][0], 'Applications')
        self.assertEqual(parts[0][1], messages.DRAG_NAME_PITCH)
        self.assertIn('2', parts[1][0])
        self.assertEqual(parts[1][1], 0)
        self.assertTrue(recorder.said[0].replaces_focus)

    def test_the_dragged_card_still_says_its_name_and_where_it_went(self):
        recorder = Recorder(replaces_focus=True)
        with Swap(self, recorder):
            messages.announce_drag_move('Applications', 2)
        line = recorder.said[0].sentence()
        self.assertIn('Applications', line)
        self.assertIn('2', line)

    def test_a_dragged_card_says_nothing_to_a_reader_reading_the_row_itself(self):
        recorder = Recorder(text=True)
        with Swap(self, recorder):
            self.assertFalse(messages.announce_drag_move('Applications', 2))
        self.assertEqual(recorder.said, [])


class TitanAccessHabitsReachEveryReader(unittest.TestCase):
    """Two things Titan has always known and only its own reader was told."""

    def setUp(self):
        quiet(self)

    def test_the_kind_of_dialog_is_offered_to_a_reader_that_takes_it(self):
        told = []

        class Reader(Recorder):
            def dialog_kind(self, kind, label=''):
                told.append((kind, label))
                return True

        with Swap(self, Reader(dialog_kind=True)):
            self.assertTrue(messages.announce_dialog_kind('question'))
        self.assertEqual(len(told), 1)
        kind, label = told[0]
        self.assertEqual(kind, 'question')
        # The WORD travels too: a reader add-on has no catalogue of Titan's
        # and would otherwise invent one, which is two vocabularies for one
        # desktop.
        self.assertTrue(label,
                        'the reader must be told what to say, not only which '
                        'kind it is')

    def test_the_word_is_the_one_titan_access_uses(self):
        # Where that component is installed its own catalogue wins, so a
        # user hears the same word whichever reader they are using.
        for kind in ('question', 'information', 'warning', 'error'):
            self.assertTrue(messages._dialog_kind_label(kind), kind)
        self.assertEqual(messages._dialog_kind_label('not a kind'), '')

    def test_a_reader_that_cannot_is_not_pretended_to(self):
        # The caller does something else with a False - the shutdown dialog
        # simply lets the reader read the dialog - so a True here would be
        # the worst possible answer.
        with Swap(self, Recorder(text=True)):
            self.assertFalse(messages.announce_dialog_kind('question'))

    def test_a_state_is_offered_the_same_way(self):
        told = []

        class Reader(Recorder):
            def state_suffix(self, text):
                told.append(text)
                return True

        with Swap(self, Reader(state_suffix=True)):
            self.assertTrue(messages.announce_state_suffix('checked'))
        self.assertEqual(told, ['checked'])

    def test_the_checklist_falls_back_when_the_reader_cannot_take_it(self):
        # The delayed accessible_output3 path is still the right answer for
        # a reader that can do neither, which is why this says whether it
        # was taken rather than assuming.
        delayed = []
        original = messages._speak_checklist_state_after
        messages._speak_checklist_state_after = \
            lambda checked, delay: delayed.append(checked)
        self.addCleanup(lambda: setattr(
            messages, '_speak_checklist_state_after', original))
        with Swap(self, Recorder(text=True)):
            messages.announce_checklist_item_navigation(True, delay_ms=0)
        self.assertEqual(delayed, [True])

    def test_and_does_not_fall_back_when_it_was_taken(self):
        delayed = []
        original = messages._speak_checklist_state_after
        messages._speak_checklist_state_after = \
            lambda checked, delay: delayed.append(checked)
        self.addCleanup(lambda: setattr(
            messages, '_speak_checklist_state_after', original))

        class Reader(Recorder):
            def state_suffix(self, text):
                return True

        with Swap(self, Reader(state_suffix=True)):
            messages.announce_checklist_item_navigation(True, delay_ms=0)
        self.assertEqual(delayed, [])

    def test_a_channel_with_nobody_behind_it_takes_neither(self):
        channel = reader_channel.Channel()
        self.assertFalse(channel.dialog_kind('question'))
        self.assertFalse(channel.state_suffix('checked'))


class NothingHereMayRaise(unittest.TestCase):
    """An announcement is made from a focus handler."""

    def setUp(self):
        quiet(self)

    def test_a_reader_that_throws_does_not_take_the_interface_with_it(self):
        class Broken(reader_channel.Channel):
            name = 'broken'

            def can(self, _what):
                return True

            def say(self, _message):
                raise RuntimeError('the pipe went away')

        saved = reader_channel.channel
        reader_channel.channel = lambda: Broken()
        try:
            self.assertFalse(messages._reader_announce('anything'))
        finally:
            reader_channel.channel = saved

    def test_report_answers_something_on_a_machine_with_no_reader(self):
        report = reader_channel.report()
        self.assertIn('channel', report)
        self.assertIsInstance(report['capabilities'], dict)


if __name__ == '__main__':
    unittest.main(verbosity=2)
