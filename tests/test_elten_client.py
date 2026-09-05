"""What Titan knows about the Elten client, and where it got it.

`elten_client_*` answers from one of two places and the difference matters to
whoever is reading it: the RUNNING Elten, asked over the bus and answered from
its own state, or the last report the bridge pushed, which may be minutes old.
The rule is "ask when it is there, remember when it is not", and an answer out
of the second place has to say how old it is.

    python tests/test_elten_client.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.titan_core import elten_client_actions as client


class Base(unittest.TestCase):
    def setUp(self):
        client._report.clear()
        self._ask = client._ask
        self._connected = client._connected
        client._connected = lambda: False

    def tearDown(self):
        client._ask = self._ask
        client._connected = self._connected
        client._report.clear()

    def nothing_there(self):
        client._ask = lambda action: (False, None)

    def answers(self, table):
        client._ask = lambda action: (True, table[action])


class WhenEltenIsNotThere(Base):
    def test_it_says_so_and_says_what_to_do(self):
        self.nothing_there()
        said = client.elten_client_status()
        self.assertIn('not running', said)
        # The one thing the user can act on: it may simply not have been
        # allowed to share yet.
        self.assertIn('permission', said)

    def test_the_last_report_is_used_and_dated(self):
        self.nothing_there()
        client.report({'user': 'tito', 'version': '3.0.2',
                       'notifications': [{'text': 'x', 'cat': 'message'}]})
        client._report[client.CLIENT_ID]['at'] -= 30
        said = client.elten_client_status()
        self.assertIn('tito', said)
        self.assertIn('last said', said)
        self.assertIn('30 seconds ago', said)

    def test_a_report_that_is_very_old_says_so_differently(self):
        self.nothing_there()
        client.report({'user': 'tito', 'notifications': []})
        client._report[client.CLIENT_ID]['at'] -= client.STALE_AFTER + 60
        self.assertIn('last heard', client.elten_client_status())


class WhenEltenIsThere(Base):
    def test_the_live_answer_wins_over_the_remembered_one(self):
        client.report({'user': 'stale', 'notifications': []})
        self.answers({'status': {'running': True, 'user': 'live',
                                 'version': '3.0.2', 'notifications': 2}})
        said = client.elten_client_status()
        self.assertIn('live', said)
        self.assertNotIn('stale', said)
        # A live answer must not be prefaced with "this is what it last
        # said": it is what Elten is saying now.
        self.assertNotIn('last said', said)
        self.assertIn('connected', said)

    def test_the_notifications_are_the_ones_elten_holds_now(self):
        self.answers({'notifications': {'notifications': [
            {'text': 'Nowa wiadomosc', 'cat': 'message'},
            {'text': 'Odpowiedz', 'cat': 'forum'}]}})
        said = client.elten_client_notifications()
        self.assertIn('Nowa wiadomosc', said)
        self.assertIn('[forum]', said)
        self.assertIn('2 notification', said)

    def test_the_counts_are_said_in_words(self):
        self.answers({'news': {'news': {'notifications': 3, 'message': 1,
                                        'forum': 2}}})
        said = client.elten_client_news()
        self.assertIn('private messages', said)
        self.assertIn('forum replies', said)

    def test_a_refusal_is_passed_through_as_it_was_said(self):
        """The bridge answers a sentence rather than a shape when it will
        not share - permission taken back, usually - and that sentence is
        the answer, not an error to translate into an empty Elten."""
        self.answers({'notifications':
                      'Elten has not been given permission to share its '
                      'data with Titan.'})
        self.assertIn('permission', client.elten_client_notifications())


class TheScreen(Base):
    """Elten is self-voicing, so "what is on the screen" is what it last
    said plus the controls the current screen is holding. These have no
    remembered half on purpose: a minute-old screen is not a worse answer,
    it is a wrong one."""

    SCREEN = {
        'said': 'Wiadomosci, lista, 3 elementy',
        'scene': 'Messages',
        'controls': [{'kind': 'form', 'controls': [
            {'kind': 'list', 'header': 'Wiadomosci', 'count': 3, 'index': 0,
             'current': 'Od Dawida', 'focused': True},
            {'kind': 'field', 'header': 'Tresc', 'text': '', 'focused': False},
            {'kind': 'button', 'label': 'Wyslij', 'focused': False}]}],
    }

    def answers_with(self, table):
        client._ask_with = lambda action, args: (
            (True, table[action]) if action in table else (False, None))

    def tearDown(self):
        super().tearDown()
        client._ask_with = client.__dict__.get('_ask_with')

    def test_the_screen_is_read_as_words(self):
        self.answers_with({'screen': self.SCREEN})
        said = client.elten_client_screen()
        self.assertIn('Messages', said)
        self.assertIn('Wiadomosci, lista, 3 elementy', said)
        self.assertIn('Od Dawida', said)
        self.assertIn('Wyslij', said)

    def test_the_focused_control_is_marked(self):
        self.answers_with({'screen': self.SCREEN})
        said = client.elten_client_screen()
        marked = [line for line in said.split('\n') if 'keyboard is here' in line]
        self.assertEqual(len(marked), 1, said)
        self.assertIn('Od Dawida', marked[0])

    def test_no_elten_is_said_plainly(self):
        self.answers_with({})
        for answer in (client.elten_client_screen(),
                       client.elten_client_programs(),
                       client.elten_client_run_program(name='anything')):
            self.assertIn('not running', answer)

    def test_a_refusal_comes_through_as_the_sentence_it_is(self):
        self.answers_with({'screen': 'Elten has not been given permission '
                                     'to share its data with Titan.'})
        self.assertIn('permission', client.elten_client_screen())

    def test_the_programs_are_listed_by_name(self):
        self.answers_with({'programs': {'programs': [
            {'name': 'File manager'}, {'name': 'TCE bridge'}]}})
        said = client.elten_client_programs()
        self.assertIn('File manager', said)
        self.assertIn('TCE bridge', said)

    def test_opening_one_says_which(self):
        self.answers_with({'run_program': {'opened': 'File manager'}})
        self.assertIn('File manager',
                      client.elten_client_run_program(name='file'))

    def test_a_program_that_is_not_there_is_a_stated_failure(self):
        self.answers_with({'run_program': {'error': "Elten has no program "
                                                    "called 'nothing'"}})
        answer = client.elten_client_run_program(name='nothing')
        # `fails` carries the reason rather than reading as success.
        self.assertIn('nothing', str(answer))

    def test_no_name_is_a_question_rather_than_a_guess(self):
        self.answers_with({'run_program': {'opened': 'x'}})
        answer = client.elten_client_run_program(name='')
        self.assertIn('Which', str(answer))


class TheActionsAreOffered(unittest.TestCase):
    def test_every_one_of_them_is_registered_and_runs(self):
        from src.titan_core import actions
        addon = next((a for a in actions.list_addons()
                      if a['id'] == 'elten_client'), None)
        self.assertIsNotNone(addon, "the elten_client provider is missing")
        for name in ('status', 'notifications', 'news', 'report',
                     'screen', 'programs'):
            self.assertIn(name, addon['actions'])
            result = actions.run('elten_client', name)
            self.assertTrue(result.ok, f"{name}: {result.text}")

    def test_the_assistant_has_them_as_tools(self):
        from src.ai.tools import get_subsystem_tools
        names = {tool['name'] for tool in get_subsystem_tools()}
        for wanted in ('elten_client_status', 'elten_client_notifications',
                       'elten_client_news', 'elten_client_screen',
                       'elten_client_programs', 'elten_client_run_program'):
            self.assertIn(wanted, names)

    def test_opening_a_program_in_elten_is_confirmed_first(self):
        """It happens in front of whoever is sitting at Elten, which is not
        necessarily the person talking to the assistant."""
        from src.ai.tools import get_subsystem_tools
        tool = next(t for t in get_subsystem_tools()
                    if t['name'] == 'elten_client_run_program')
        self.assertTrue(tool['always_confirm'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
