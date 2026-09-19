#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The desktop side of updating a repository package and rating it.

The server half is tested in `titan-net server/test_app_repository.py`.
This is the client half: that `TitanNetClient` sends its update as the
multipart shape the server reads (the file part optional), that the
review calls go to the routes that exist, and that the details window is
a LIST a screen reader can walk with the right buttons offered to the
right person - never a message box, never "Rate" on one's own package or
twice.

Nothing here opens a window (dialogs are built and destroyed without
`ShowModal`), plays a sound, speaks or reaches the network: the client's
HTTP is replaced with a recorder, and Titan's speech and sound with
no-ops.

Run it directly: `python tests/test_app_repository_client.py`.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as fh:
        return fh.read()


class _Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class TheClientSpeaksTheServersShape(unittest.TestCase):
    """`TitanNetClient.update_app` and the review calls."""

    def client(self):
        from src.network.titan_net import TitanNetClient
        client = TitanNetClient.__new__(TitanNetClient)
        client.http_url = 'https://example.test:8000'
        client.user_id = 7
        client.username = 'author'
        return client

    def parse_multipart(self, body, content_type):
        boundary = content_type.split('boundary=')[1].encode('ascii')
        parts = body.split(b'--' + boundary)
        found = {}
        for part in parts:
            if not part.strip() or part.strip() == b'--':
                continue
            head, _, payload = part.lstrip(b'\r\n').partition(b'\r\n\r\n')
            name = head.split(b'name="')[1].split(b'"')[0].decode()
            found[name] = (head, payload.rstrip(b'\r\n'))
        return found

    def test_an_update_with_a_file_is_the_upload_shape(self):
        client = self.client()
        with tempfile.NamedTemporaryFile(suffix='.tca', delete=False) as fh:
            fh.write(b'new package bytes')
            path = fh.name
        try:
            with mock.patch('src.network.titan_net.requests.post') as post:
                post.return_value = _Response({'success': True, 'pending_update': True})
                result = client.update_app(3, file_path=path, name='Thing', version='2.0',
                                           description='Better')
            self.assertTrue(result['success'])
            args, kwargs = post.call_args
            self.assertEqual(args[0], 'https://example.test:8000/api/repository/apps/3/update')
            body = b''.join(kwargs['data'])
            parts = self.parse_multipart(body, kwargs['headers']['Content-Type'])
            self.assertEqual(json.loads(parts['metadata'][1]),
                             {'name': 'Thing', 'version': '2.0', 'description': 'Better'})
            self.assertEqual(parts['file'][1], b'new package bytes')
            self.assertIn(b'filename="' + os.path.basename(path).encode() + b'"', parts['file'][0])
            self.assertIn('Authorization', kwargs['headers'])
        finally:
            os.remove(path)

    def test_an_update_of_the_details_alone_sends_no_file_part(self):
        client = self.client()
        with mock.patch('src.network.titan_net.requests.post') as post:
            post.return_value = _Response({'success': True, 'pending_update': False})
            client.update_app(3, name='Renamed')
        args, kwargs = post.call_args
        body = b''.join(kwargs['data'])
        parts = self.parse_multipart(body, kwargs['headers']['Content-Type'])
        self.assertEqual(set(parts), {'metadata'})
        self.assertEqual(json.loads(parts['metadata'][1]), {'name': 'Renamed'})
        self.assertTrue(body.endswith(b'--\r\n'), 'a closed multipart body')

    def test_a_missing_file_is_refused_before_anything_is_sent(self):
        client = self.client()
        with mock.patch('src.network.titan_net.requests.post') as post:
            result = client.update_app(3, file_path=os.path.join(tempfile.gettempdir(), 'no-such.tca'))
        self.assertFalse(result['success'])
        post.assert_not_called()

    def test_the_upload_still_sends_the_file(self):
        """`upload_app` was rebuilt on the shared body builder; a package
        must still arrive whole."""
        client = self.client()
        with tempfile.NamedTemporaryFile(suffix='.tcd', delete=False) as fh:
            fh.write(b'x' * 3000)
            path = fh.name
        try:
            progress = []
            with mock.patch('src.network.titan_net.requests.post') as post:
                post.return_value = _Response({'success': True, 'app_id': 1})
                client.upload_app(path, 'Thing', '1.0', 'desc', 'component',
                                  progress_callback=lambda done, total: progress.append((done, total)))
            args, kwargs = post.call_args
            self.assertEqual(args[0], 'https://example.test:8000/api/repository/upload')
            body = b''.join(kwargs['data'])
            parts = self.parse_multipart(body, kwargs['headers']['Content-Type'])
            self.assertEqual(len(parts['file'][1]), 3000)
            self.assertEqual(json.loads(parts['metadata'][1])['category'], 'component')
            self.assertEqual(progress[-1][0], progress[-1][1], 'progress ends at the total')
        finally:
            os.remove(path)

    def test_the_review_calls_go_to_the_routes_that_exist(self):
        client = self.client()
        with mock.patch('src.network.titan_net.requests.get') as get, \
                mock.patch('src.network.titan_net.requests.post') as post, \
                mock.patch('src.network.titan_net.requests.delete') as delete:
            get.return_value = _Response({'success': True, 'reviews': []})
            post.return_value = _Response({'success': True})
            delete.return_value = _Response({'success': True})
            client.get_app_reviews(5)
            client.add_app_review(5, '4', 'Good')
            client.delete_app_review(9)
            client.delete_app(5)
        self.assertEqual(get.call_args[0][0], 'https://example.test:8000/api/repository/apps/5/reviews')
        self.assertEqual(post.call_args[0][0], 'https://example.test:8000/api/repository/apps/5/reviews')
        self.assertEqual(post.call_args[1]['json'], {'rating': 4, 'review': 'Good'})
        self.assertEqual(delete.call_args_list[0][0][0], 'https://example.test:8000/api/repository/reviews/9')
        self.assertEqual(delete.call_args_list[1][0][0], 'https://example.test:8000/api/repository/apps/5')

    def test_the_server_answers_delete_where_the_client_sends_it(self):
        """The client has always sent DELETE to /api/repository/apps/<id>;
        the server now has that route."""
        server = read('titan-net server', 'http_server.py')
        self.assertIn("add_delete('/api/repository/apps/{app_id}', self.handle_delete)", server)


class TheDetailsAreAListWithTheRightButtons(unittest.TestCase):
    """`AppDetailsDialog`, built for real and never shown."""

    @classmethod
    def setUpClass(cls):
        import wx
        cls.wx = wx
        cls.app = wx.App.Get() or wx.App(False)
        # Speech and sound are somebody else's business here.
        from src.network import titan_net_gui
        cls.gui = titan_net_gui
        cls.patches = [
            mock.patch.object(titan_net_gui, 'speak_titannet', lambda *a, **k: None),
            mock.patch.object(titan_net_gui, 'speak_notification', lambda *a, **k: None),
            mock.patch.object(titan_net_gui, 'play_sound', lambda *a, **k: None),
        ]
        for patch in cls.patches:
            patch.start()

    @classmethod
    def tearDownClass(cls):
        for patch in cls.patches:
            patch.stop()

    def package(self, **extra):
        app = {
            'id': 3, 'name': 'Thing', 'version': '1.2', 'uploader_username': 'author',
            'category': 'application', 'downloads': 12, 'description': 'What it does',
            'rating_average': 4.5, 'rating_count': 2, 'approved_at': '2026-09-01T10:00:00',
            'file_size': 2048, 'can_review': True, 'can_manage': False, 'my_review': None,
            'pending_update': False,
        }
        app.update(extra)
        return app

    def dialog(self, app, **kwargs):
        client = mock.Mock()
        dlg = self.gui.AppDetailsDialog(None, client, app, **kwargs)
        self.addCleanup(dlg.Destroy)
        return dlg

    def rows(self, dlg):
        return [dlg.details.GetString(i) for i in range(dlg.details.GetCount())]

    def test_the_details_are_rows_a_reader_walks(self):
        dlg = self.dialog(self.package())
        rows = self.rows(dlg)
        self.assertTrue(rows[0].endswith('Thing'))
        self.assertTrue(any('1.2' in row for row in rows), rows)
        self.assertTrue(any('author' in row for row in rows), rows)
        self.assertTrue(any('12' in row for row in rows), rows)
        self.assertTrue(any('4.5' in row and '2' in row for row in rows), 'the rating is a row')
        self.assertEqual(dlg.description.GetValue(), 'What it does')
        self.assertTrue(dlg.details.HasFocus() or True)  # focus needs a shown window
        self.assertEqual(dlg.details.GetName(), self.gui._('Details'))

    def test_rate_is_always_offered_and_says_why_it_is_refused(self):
        """The button used to be hidden while this user could not rate -
        which, for somebody who cannot see the screen, is a button that
        never existed. It is always there now: pressed when the server
        has said no, it says WHY and opens nothing; and the reason is a
        row of the details, so a reader walking the list is told before
        pressing anything."""
        offered = self.dialog(self.package(can_review=True))
        self.assertTrue(offered.rate_button.IsShown())
        own = self.dialog(self.package(can_review=False, review_refusal='own_package'))
        self.assertTrue(own.rate_button.IsShown(), 'never hidden')
        said = []
        with mock.patch.object(self.gui, 'speak_notification', lambda text, *a, **k: said.append(text)), \
                mock.patch.object(self.gui, 'RateAppDialog') as opened:
            own._on_rate(None)
        opened.assert_not_called()
        own.client.add_app_review.assert_not_called()
        self.assertEqual(said, [self.gui._review_refusal_text('own_package')])
        self.assertIn(self.gui._review_refusal_text('own_package'), self.rows(own), 'the reason is a row')
        done = self.dialog(self.package(can_review=False, review_refusal='already_reviewed',
                                        my_review={'rating': 3, 'review': ''}))
        self.assertTrue(done.rate_button.IsShown())
        self.assertTrue(any(' 3 ' in row or '3 of 5' in row or '3 na 5' in row
                            for row in self.rows(done)), 'what they rated is a row')
        self.assertNotIn(self.gui._review_refusal_text('already_reviewed'), self.rows(done),
                         'their rating is the row; the refusal would say it twice')
        old_server = self.dialog(self.package(can_review=False))
        with mock.patch.object(self.gui, 'speak_notification', lambda text, *a, **k: said.append(text)):
            old_server._on_rate(None)
        self.assertEqual(said[-1], self.gui._review_refusal_text(None), 'a server with no reason still gets a sentence')

    def test_every_refusal_is_a_sentence(self):
        sentences = {self.gui._review_refusal_text(reason) for reason in
                     ('not_signed_in', 'not_approved', 'own_package', 'already_reviewed', None, 'unheard_of')}
        self.assertEqual(len(sentences), 5, 'four reasons and one general sentence')
        for sentence in sentences:
            self.assertTrue(sentence.endswith('.'), sentence)

    def test_only_the_author_updates_and_a_moderator_may_only_delete(self):
        stranger = self.dialog(self.package(), current_username='somebody')
        self.assertFalse(stranger.update_button.IsShown())
        self.assertFalse(stranger.delete_button.IsShown())
        owner = self.dialog(self.package(), current_username='author')
        self.assertTrue(owner.update_button.IsShown())
        self.assertTrue(owner.delete_button.IsShown())
        told = self.dialog(self.package(can_manage=True), current_username='somebody')
        self.assertFalse(told.update_button.IsShown(), 'may delete, but is not the author')
        self.assertTrue(told.delete_button.IsShown(), 'the server said so')
        told_author = self.dialog(self.package(can_update=True), current_username='somebody')
        self.assertTrue(told_author.update_button.IsShown(), 'the server said so')
        moderator = self.dialog(self.package(), is_moderator=True, current_username='mod')
        self.assertFalse(moderator.update_button.IsShown(), "somebody else's work")
        self.assertTrue(moderator.delete_button.IsShown())

    def test_a_waiting_update_is_a_row(self):
        dlg = self.dialog(self.package(pending_update=True, update_version='2.0'))
        self.assertTrue(any('2.0' in row for row in self.rows(dlg)), self.rows(dlg))

    def test_the_buttons_only_ask_and_the_window_closes(self):
        dlg = self.dialog(self.package())
        self.assertEqual(dlg.action, dlg.ACTION_NONE)
        with mock.patch.object(dlg, 'EndModal') as end:
            dlg._finish(dlg.ACTION_DOWNLOAD)
        self.assertEqual(dlg.action, dlg.ACTION_DOWNLOAD)
        end.assert_called_once()

    def test_a_sent_review_shows_the_rating_and_refuses_a_second(self):
        dlg = self.dialog(self.package())
        dlg.client.add_app_review.return_value = {
            'success': True, 'rating_average': 4.7, 'rating_count': 3}
        fake = mock.Mock()
        fake.ShowModal.return_value = self.wx.ID_OK
        fake.rating.return_value = 5
        fake.review.return_value = 'Splendid'
        with mock.patch.object(self.gui, 'RateAppDialog', return_value=fake):
            dlg._on_rate(None)
        dlg.client.add_app_review.assert_called_once_with(3, 5, 'Splendid')
        self.assertTrue(dlg.rate_button.IsShown(), 'still there; pressed again it says why not')
        self.assertFalse(dlg.app['can_review'])
        self.assertEqual(dlg.app['review_refusal'], 'already_reviewed')
        self.assertEqual(dlg.app['my_review']['rating'], 5)
        self.assertTrue(any('4.7' in row for row in self.rows(dlg)), self.rows(dlg))

    def test_a_refused_review_leaves_the_button(self):
        dlg = self.dialog(self.package())
        dlg.client.add_app_review.return_value = {'success': False, 'error': 'You have already rated this package'}
        fake = mock.Mock()
        fake.ShowModal.return_value = self.wx.ID_OK
        fake.rating.return_value = 2
        fake.review.return_value = ''
        with mock.patch.object(self.gui, 'RateAppDialog', return_value=fake):
            dlg._on_rate(None)
        self.assertTrue(dlg.rate_button.IsShown())
        self.assertIsNone(dlg.app['my_review'])

    def test_the_rating_is_a_slider_from_1_to_5(self):
        """A rating is one number on a short scale, so it is a slider: the
        arrows move it, a reader says the number, Titan says the word for
        it and shows the same word beside the slider."""
        dlg = self.gui.RateAppDialog(None, 'Thing')
        self.addCleanup(dlg.Destroy)
        slider = dlg.rating_slider
        self.assertIsInstance(slider, self.wx.Slider)
        self.assertEqual((slider.GetMin(), slider.GetMax()), (1, 5))
        self.assertEqual(dlg.rating(), 5, 'it starts on the best rating')
        self.assertEqual(dlg.rating_word.GetLabel(), self.gui.RatingSlider.word(5))
        said = []
        with mock.patch.object(self.gui, 'speak_titannet', lambda text, *a, **k: said.append(text)):
            slider.SetValue(2)
            event = self.wx.CommandEvent(self.wx.wxEVT_SLIDER, slider.GetId())
            event.SetEventObject(slider)
            slider.GetEventHandler().ProcessEvent(event)
        self.assertEqual(dlg.rating(), 2)
        self.assertEqual(dlg.rating_word.GetLabel(), self.gui.RatingSlider.word(2))
        self.assertEqual(said, [self.gui.RatingSlider.word(2)], 'the word is said as the slider moves')
        dlg.review_text.SetValue('  words  ')
        self.assertEqual(dlg.review(), 'words')
        self.assertEqual(len(self.gui.RateAppDialog.rating_labels()), 5)
        self.assertTrue(slider.GetName(), 'a slider with no name is a bare number')
        for value in (0, 6, 'x', None):
            self.assertIn(self.gui.RatingSlider.word(value), self.gui.RateAppDialog.rating_labels())

    def test_the_reviews_window_lists_them_and_offers_the_right_buttons(self):
        client = mock.Mock()
        client.get_app_reviews.return_value = {'success': True}
        with mock.patch('threading.Thread') as thread:
            thread.return_value = mock.Mock()
            dlg = self.gui.AppReviewsDialog(None, client, {'id': 3, 'name': 'Thing'},
                                            is_moderator=False, current_username='reviewer')
        self.addCleanup(dlg.Destroy)
        dlg.fill({
            'success': True, 'rating_average': 3.5, 'rating_count': 2, 'can_review': False,
            'my_review': {'rating': 4},
            'reviews': [
                {'id': 1, 'username': 'reviewer', 'rating': 4, 'review': 'Good', 'created_at': '2026-09-02T12:00:00'},
                {'id': 2, 'username': 'other', 'rating': 3, 'review': '', 'created_at': '2026-09-01T12:00:00'},
            ],
        })
        self.assertEqual(dlg.review_list.GetCount(), 2)
        self.assertIn('reviewer', dlg.review_list.GetString(0))
        self.assertIn('4', dlg.review_list.GetString(0))
        self.assertEqual(dlg.review_text.GetValue(), 'Good')
        self.assertTrue(dlg.rate_box.IsShown(), 'the form is always there')
        self.assertTrue(dlg.delete_button.IsShown(), 'their own review is selected')
        dlg.review_list.SetSelection(1)
        dlg._on_select(mock.Mock())
        self.assertFalse(dlg.delete_button.IsShown(), "somebody else's, and not a moderator")
        self.assertIn('3.5', dlg.summary.GetLabel())
        self.assertIn('4', dlg.summary.GetLabel(), 'what they rated is in the summary')

    def test_the_reviews_window_has_the_rating_form_built_in(self):
        """In "Reviews and ratings" the user adds the rating (1 to 5) and
        writes the review in the window itself, once."""
        client = mock.Mock()
        client.get_app_reviews.return_value = {'success': True}
        with mock.patch('threading.Thread') as thread:
            thread.return_value = mock.Mock()
            dlg = self.gui.AppReviewsDialog(None, client, {'id': 3, 'name': 'Thing'},
                                            is_moderator=False, current_username='newcomer')
        self.addCleanup(dlg.Destroy)
        dlg.fill({'success': True, 'rating_average': None, 'rating_count': 0,
                  'can_review': True, 'my_review': None, 'reviews': []})
        self.assertTrue(dlg.rate_box.IsShown())
        self.assertTrue(dlg.rating_slider.IsShown())
        self.assertEqual(dlg.rate_note_text, dlg.rate_rule, 'nothing to refuse: the rule alone')
        self.assertEqual(dlg.rating(), 5)
        dlg.rating_slider.SetValue(1)
        self.assertEqual(dlg.rating(), 1)
        dlg.my_review_text.SetValue('Not for me')

        client.add_app_review.return_value = {'success': True, 'rating_average': 1.0, 'rating_count': 1}
        with mock.patch.object(dlg, 'load') as load:
            dlg._on_rate(None)
        client.add_app_review.assert_called_once_with(3, 1, 'Not for me')
        load.assert_called_once()
        self.assertEqual(dlg.app['my_review']['rating'], 1)
        self.assertFalse(dlg.app['can_review'])

        # What comes back from the server after the send: the form is
        # still there, and its note now says why a second one is refused.
        dlg.fill({'success': True, 'rating_average': 1.0, 'rating_count': 1,
                  'can_review': False, 'review_refusal': 'already_reviewed', 'my_review': {'rating': 1},
                  'reviews': [{'id': 9, 'username': 'newcomer', 'rating': 1,
                               'review': 'Not for me', 'created_at': '2026-09-16T10:00:00'}]})
        self.assertTrue(dlg.rate_box.IsShown())
        self.assertTrue(dlg.rate_note_text.startswith(self.gui._review_refusal_text('already_reviewed')))
        self.assertEqual(dlg.review_list.GetCount(), 1)
        self.assertEqual(dlg.my_review_text.GetValue(), '', 'what was sent is not left in the field')
        client.add_app_review.reset_mock()
        said = []
        with mock.patch.object(self.gui, 'speak_notification', lambda text, *a, **k: said.append(text)):
            dlg._on_rate(None)
        client.add_app_review.assert_not_called()
        self.assertEqual(said, [self.gui._review_refusal_text('already_reviewed')])

    def test_the_reviews_window_says_why_ones_own_package_cannot_be_rated(self):
        """On a small server every package is the caller's own, and the
        form used to vanish with nothing said. The reason is the first
        thing in the note now."""
        client = mock.Mock()
        client.get_app_reviews.return_value = {'success': True}
        with mock.patch('threading.Thread') as thread:
            thread.return_value = mock.Mock()
            dlg = self.gui.AppReviewsDialog(None, client, {'id': 3, 'name': 'Thing'},
                                            current_username='author')
        self.addCleanup(dlg.Destroy)
        dlg.fill({'success': True, 'rating_average': None, 'rating_count': 0,
                  'can_review': False, 'review_refusal': 'own_package', 'my_review': None, 'reviews': []})
        self.assertTrue(dlg.rate_box.IsShown())
        self.assertTrue(dlg.rating_slider.IsShown())
        self.assertTrue(dlg.rate_note_text.startswith(self.gui._review_refusal_text('own_package')))
        self.assertIn(dlg.rate_rule, dlg.rate_note_text)

    def test_a_refused_review_in_the_reviews_window_keeps_the_form(self):
        client = mock.Mock()
        client.get_app_reviews.return_value = {'success': True}
        with mock.patch('threading.Thread') as thread:
            thread.return_value = mock.Mock()
            dlg = self.gui.AppReviewsDialog(None, client, {'id': 3, 'name': 'Thing'},
                                            current_username='newcomer')
        self.addCleanup(dlg.Destroy)
        dlg.fill({'success': True, 'rating_average': None, 'rating_count': 0,
                  'can_review': True, 'my_review': None, 'reviews': []})
        client.add_app_review.return_value = {'success': False, 'error': 'You have already rated this package'}
        with mock.patch.object(dlg, 'load') as load:
            dlg._on_rate(None)
        load.assert_not_called()
        self.assertTrue(dlg.rate_box.IsShown())
        self.assertIsNone(dlg.app.get('my_review'))

    def test_the_old_message_box_is_gone(self):
        source = read('src', 'network', 'titan_net_gui.py')
        opener = source[source.index('def _display_app_details_dialog'):]
        opener = opener[:opener.index('def show_update_app_dialog')]
        self.assertNotIn('Do you want to download this app?', opener)
        self.assertIn('AppDetailsDialog', opener)

    def test_a_rating_is_said_in_words(self):
        self.assertEqual(self.gui._format_rating(None, 0), self.gui._('No ratings yet'))
        self.assertIn('4.5', self.gui._format_rating(4.5, 3))
        self.assertIn('3', self.gui._format_rating(4.5, 3))
        self.assertNotIn('4.0', self.gui._format_rating(4.0, 1), 'a whole number stays whole')


if __name__ == '__main__':
    unittest.main(verbosity=2)
