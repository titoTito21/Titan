# -*- coding: utf-8 -*-
"""
Regression tests for moving a forum thread between groups.

Reported symptom: moving a thread into a group the reporter also OWNS produced
no notification and no confirmation question. Two causes:

* ``request_topic_move`` filed a pending approval request for every cross-group
  move, including one the requester was entitled to approve themselves - so the
  thread stayed put and the "request" waited on its own author.
* nothing ever told the target group's moderators that a request existed.

These run against a real (temporary) server database so the SQL is exercised,
not mocked.
"""

import os
import re
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'titan-net server'))


def _load_database():
    """Import the server's Database class, skipping if its deps are absent."""
    try:
        import models
    except Exception as e:            # pragma: no cover - optional server deps
        raise unittest.SkipTest(f"server models unavailable: {e}")
    return models


class ThreadMoveTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.models = _load_database()
        fd, cls.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        os.unlink(cls.db_path)
        try:
            cls.db = cls.models.Database(cls.db_path)
        except TypeError:
            cls.db = cls.models.Database(db_path=cls.db_path)
        except Exception as e:        # pragma: no cover
            raise unittest.SkipTest(f"cannot open a test database: {e}")

    @classmethod
    def tearDownClass(cls):
        for suffix in ('', '-wal', '-shm'):
            try:
                os.unlink(cls.db_path + suffix)
            except OSError:
                pass

    # -- helpers ---------------------------------------------------------

    def _user(self, name):
        result = self.db.create_user(name, "Passw0rd!123", full_name=name,
                                     email=f"{name}@example.test")
        self.assertTrue(result.get('success'), result)
        user_id = result.get('user_id') or result.get('id')
        self.assertIsNotNone(user_id, result)
        return user_id

    def _group(self, owner_id, name):
        result = self.db.create_group(name, 'test group', owner_id)
        self.assertTrue(result.get('success'), result)
        return result.get('group_id') or result.get('id')

    def _forum(self, group_id, owner_id, name):
        result = self.db.create_group_forum(group_id, name, 'desc', owner_id)
        self.assertTrue(result.get('success'), result)
        return result.get('forum_id') or result.get('id')

    def _topic(self, forum_id, author_id, title):
        result = self.db.create_forum_topic(title, 'body', author_id, forum_id=forum_id)
        self.assertTrue(result.get('success'), result)
        return result.get('topic_id') or result.get('id')

    def _forum_of(self, topic_id):
        topic = self.db.get_forum_topic(topic_id)
        return topic.get('forum_id') if topic else None

    # -- the reported bug ------------------------------------------------

    def test_move_into_a_second_group_you_own_happens_immediately(self):
        """The reported case: owner of both groups, so nobody is left to ask."""
        owner = self._user('owner_both')
        group_a = self._group(owner, 'Group A')
        group_b = self._group(owner, 'Group B')
        forum_a = self._forum(group_a, owner, 'Forum A')
        forum_b = self._forum(group_b, owner, 'Forum B')
        topic = self._topic(forum_a, owner, 'Thread to move')

        result = self.db.request_topic_move(topic, forum_b, owner)

        self.assertTrue(result.get('success'), result)
        self.assertEqual(result.get('status'), 'moved',
                         "a move into your own group still needs approval")
        self.assertEqual(self._forum_of(topic), forum_b,
                         "the thread did not actually move")

    def test_immediate_move_reports_both_ends(self):
        """The response must name source and destination for the announcement."""
        owner = self._user('owner_names')
        group_a = self._group(owner, 'Names A')
        group_b = self._group(owner, 'Names B')
        forum_a = self._forum(group_a, owner, 'From Forum')
        forum_b = self._forum(group_b, owner, 'To Forum')
        topic = self._topic(forum_a, owner, 'Named thread')

        result = self.db.request_topic_move(topic, forum_b, owner)

        self.assertEqual(result.get('from_forum_name'), 'From Forum')
        self.assertEqual(result.get('to_forum_name'), 'To Forum')
        self.assertEqual(result.get('to_group_name'), 'Names B')
        self.assertEqual(result.get('title'), 'Named thread')
        self.assertTrue(result.get('cross_group'))

    def test_same_group_move_is_still_immediate(self):
        owner = self._user('owner_same')
        group = self._group(owner, 'Same Group')
        forum_one = self._forum(group, owner, 'One')
        forum_two = self._forum(group, owner, 'Two')
        topic = self._topic(forum_one, owner, 'Same-group thread')

        result = self.db.request_topic_move(topic, forum_two, owner)

        self.assertEqual(result.get('status'), 'moved')
        self.assertFalse(result.get('cross_group'))
        self.assertEqual(self._forum_of(topic), forum_two)

    def test_move_into_a_stranger_group_still_needs_approval(self):
        """Approval must survive for the case it was written for."""
        mover = self._user('mover_stranger')
        stranger = self._user('stranger_owner')
        mine = self._group(mover, 'My Group')
        theirs = self._group(stranger, 'Their Group')
        forum_mine = self._forum(mine, mover, 'Mine')
        forum_theirs = self._forum(theirs, stranger, 'Theirs')
        topic = self._topic(forum_mine, mover, 'Pushy thread')

        result = self.db.request_topic_move(topic, forum_theirs, mover)

        self.assertEqual(result.get('status'), 'pending')
        self.assertIsNotNone(result.get('request_id'))
        self.assertEqual(self._forum_of(topic), forum_mine,
                         "thread moved without approval")

    def test_target_moderators_are_discoverable_for_notification(self):
        """The notifier needs the ids of whoever can approve."""
        stranger = self._user('notify_owner')
        group = self._group(stranger, 'Notify Group')
        ids = self.db.list_group_moderator_ids(group)
        self.assertIn(stranger, ids, "the group owner must be notifiable")

    def test_non_moderator_of_source_cannot_move(self):
        owner = self._user('src_owner')
        outsider = self._user('src_outsider')
        group = self._group(owner, 'Guarded Group')
        forum_one = self._forum(group, owner, 'G1')
        forum_two = self._forum(group, owner, 'G2')
        topic = self._topic(forum_one, owner, 'Guarded thread')

        result = self.db.request_topic_move(topic, forum_two, outsider)

        self.assertFalse(result.get('success'))
        self.assertEqual(self._forum_of(topic), forum_one)


class MoveNotificationWiringTest(unittest.TestCase):
    """Source-level checks: the notification path must exist and be called."""

    def _read(self, *parts):
        with open(os.path.join(REPO, *parts), encoding='utf-8', errors='replace') as fh:
            return fh.read()

    def test_http_handler_notifies_after_a_move(self):
        source = self._read('titan-net server', 'http_server.py')
        self.assertIn('async def _notify_topic_move', source)
        self.assertIn('await self._notify_topic_move(user, result)', source)

    def test_pending_moves_notify_every_target_moderator(self):
        source = self._read('titan-net server', 'http_server.py')
        start = source.index('async def _notify_topic_move')
        body = source[start:source.index('async def handle_move_topic', start)]
        self.assertIn('list_group_moderator_ids', body)
        self.assertIn('for moderator_id in moderator_ids', body)

    def test_client_dispatches_both_move_events(self):
        source = self._read('src', 'network', 'titan_net.py')
        self.assertIn("msg_type == 'forum_topic_moved'", source)
        self.assertIn("msg_type == 'forum_move_request'", source)

    def test_gui_registers_and_implements_both_handlers(self):
        source = self._read('src', 'network', 'titan_net_gui.py')
        self.assertIn('self.titan_client.on_forum_topic_moved = self._on_forum_topic_moved', source)
        self.assertIn('self.titan_client.on_forum_move_request = self._on_forum_move_request', source)
        self.assertIn('def _on_forum_topic_moved', source)
        self.assertIn('def _on_forum_move_request', source)

    def test_move_asks_for_confirmation_naming_both_ends(self):
        """The missing "move from X to Y?" question."""
        source = self._read('src', 'network', 'titan_net_gui.py')
        start = source.index('def _mod_move_selected_topic_to_forum')
        body = source[start:start + 4000]
        self.assertIn('_show_titannet_message', body)
        self.assertIn('wx.YES_NO', body)
        self.assertIn('wx.ID_YES', body)
        self.assertRegex(body, r"Move the thread '\{title\}' from '\{source\}' to '\{destination\}'\?")

    def test_confirmation_uses_a_helper_that_exists(self):
        source = self._read('src', 'network', 'titan_net_gui.py')
        self.assertIn('def _show_titannet_message', source)

    def test_announcement_sound_file_exists(self):
        source = self._read('src', 'network', 'titan_net_gui.py')
        start = source.index('def _on_forum_move_request')
        body = source[start:start + 1200]
        sounds = re.findall(r"play_sound\('([^']+)'\)", body)
        self.assertTrue(sounds)
        for rel in sounds:
            self.assertTrue(os.path.isfile(os.path.join(REPO, 'sfx', 'default', *rel.split('/'))),
                            f"missing sound: {rel}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
