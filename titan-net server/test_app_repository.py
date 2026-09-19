#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A repository package can be updated in place, and rated once.

Two things a repository needs that this one had not got:

- **An update.** A new version used to mean deleting the package and
  sharing it again - a new id, the downloads gone, and every client's
  "seen" mark with it. Now whoever shared a package (or a moderator) sends
  a new file and it is STAGED beside the listed one: the listed file goes
  on being downloaded until a moderator approves the new one, and the
  package keeps its id, its downloads and its reviews. The details (name,
  description, version) change at once, because a name is not something
  a moderator reviews.
- **A rating and a review, once.** One per person per package, never the
  author's own, never before the package is approved. The UNIQUE
  constraint is what makes "once" true under two requests at the same
  moment; the check before it is what makes the refusal a sentence.

Run it directly: `python test_app_repository.py`. Nothing here needs
SQLCipher, a network or a running server: the HTTP handlers are driven
through aiohttp's own test client against a database in a temp folder.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:                                                    # pragma: no cover
    import argon2                                       # noqa: F401
except ImportError:
    # `models` imports the password hasher at the top. A developer's
    # machine is not the production server and a test that cannot run
    # there is a test nobody runs.
    import types

    _argon2 = types.ModuleType('argon2')
    _argon2.PasswordHasher = object
    _exceptions = types.ModuleType('argon2.exceptions')

    class _NotOurProblem(Exception):
        pass

    for _name in ('VerifyMismatchError', 'InvalidHash', 'VerificationError'):
        setattr(_exceptions, _name, _NotOurProblem)
    _argon2.exceptions = _exceptions
    sys.modules['argon2'] = _argon2
    sys.modules['argon2.exceptions'] = _exceptions

import models  # noqa: E402


def _close(db):
    """Close every pooled connection, the writer's included, or Windows
    refuses to remove the temp folder the database lives in."""
    try:
        db._writer_executor.submit(db.close_all).result(timeout=10)
    except Exception:
        pass
    try:
        db._writer_executor.shutdown(wait=True)
    except Exception:
        pass
    try:
        db.close_all()
    except Exception:
        pass


class RepositoryCase(unittest.TestCase):
    """A real database in a temp folder, an author, two other users and a
    moderator."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='titan-repo-test-')
        cls.db = models.Database(os.path.join(cls.tmp, 'repo.db'))
        # The first account on a server is its admin; nobody here is meant
        # to be one by accident.
        cls.db.create_user('root', 'password123', 'Root')
        cls.author = cls.db.create_user('author', 'password123', 'Author')['user_id']
        cls.reviewer = cls.db.create_user('reviewer', 'password123', 'Reviewer')['user_id']
        cls.other = cls.db.create_user('other', 'password123', 'Other')['user_id']
        cls.moderator = cls.db.create_user('mod', 'password123', 'Mod')['user_id']
        cls.db.set_user_role(cls.moderator, 'moderator')

    @classmethod
    def tearDownClass(cls):
        _close(cls.db)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def a_file(self, name, content=b'package bytes'):
        path = os.path.join(self.tmp, name)
        with open(path, 'wb') as fh:
            fh.write(content)
        return path

    def a_package(self, name='Thing', approved=True, version='1.0', author=None):
        path = self.a_file(f'{name}-{version}.tca')
        app_id = self.db.add_app_to_repository(
            name, 'What it does', 'application', version,
            author or self.author, path, os.path.getsize(path), {'name': name})
        if approved:
            self.assertTrue(self.db.approve_app(app_id, self.moderator))
        return app_id


class AnUpdateIsStagedBesideTheListedFile(RepositoryCase):

    def test_a_listed_package_keeps_its_file_until_the_update_is_approved(self):
        app_id = self.a_package('Staged')
        before = self.db.get_app(app_id)
        new_file = self.a_file('Staged-2.0.tca', b'new bytes')

        result = self.db.stage_app_update(app_id, new_file, 9, '2.0')

        self.assertEqual(result['mode'], 'staged')
        self.assertIsNone(result['old_file'])
        after = self.db.get_app(app_id)
        self.assertEqual(after['file_path'], before['file_path'], 'the listed file is untouched')
        self.assertEqual(after['version'], '1.0', 'the listed version is untouched')
        self.assertEqual(after['approved'], 1)
        self.assertEqual(after['update_file_path'], new_file)
        self.assertEqual(after['update_version'], '2.0')

    def test_staging_again_hands_back_the_file_it_replaces(self):
        app_id = self.a_package('Twice')
        first = self.a_file('Twice-2.0.tca')
        second = self.a_file('Twice-2.1.tca')
        self.db.stage_app_update(app_id, first, 1, '2.0')
        result = self.db.stage_app_update(app_id, second, 1, '2.1')
        self.assertEqual(result['old_file'], first)
        self.assertEqual(self.db.get_app(app_id)['update_version'], '2.1')

    def test_a_package_still_waiting_is_simply_replaced(self):
        app_id = self.a_package('Waiting', approved=False)
        old = self.db.get_app(app_id)['file_path']
        new_file = self.a_file('Waiting-1.1.tca')
        result = self.db.stage_app_update(app_id, new_file, 5, '1.1')
        self.assertEqual(result['mode'], 'replaced')
        self.assertEqual(result['old_file'], old)
        row = self.db.get_app(app_id)
        self.assertEqual(row['file_path'], new_file)
        self.assertEqual(row['version'], '1.1')
        self.assertEqual(row['approved'], 0)
        self.assertIsNone(row['update_file_path'])

    def test_an_unknown_package_is_refused(self):
        self.assertFalse(self.db.stage_app_update(999999, 'x', 1, '1.0')['success'])

    def test_approving_makes_the_update_the_listed_file(self):
        app_id = self.a_package('Goes')
        old_file = self.db.get_app(app_id)['file_path']
        new_file = self.a_file('Goes-2.0.tca', b'newer')
        self.db.stage_app_update(app_id, new_file, 5, '2.0')
        # Somebody has seen the old version; the update must show again.
        self.db.mark_app_as_seen(self.reviewer, app_id)

        moved_to = os.path.join(self.tmp, 'approved-Goes-2.0.tca')
        self.assertTrue(self.db.approve_app(app_id, self.moderator, moved_to))

        row = self.db.get_app(app_id)
        self.assertEqual(row['file_path'], moved_to)
        self.assertEqual(row['file_size'], 5)
        self.assertEqual(row['version'], '2.0')
        self.assertIsNotNone(row['updated_at'])
        self.assertIsNone(row['update_file_path'])
        self.assertIsNone(row['update_version'])
        self.assertNotEqual(row['file_path'], old_file)
        conn = self.db.get_connection()
        seen = conn.cursor().execute(
            "SELECT COUNT(*) AS n FROM app_seen_status WHERE app_id = ?", (app_id,)).fetchone()['n']
        conn.close()
        self.assertEqual(seen, 0, "everybody's seen mark is cleared")

    def test_approving_without_a_new_path_keeps_the_staged_one(self):
        app_id = self.a_package('Same')
        new_file = self.a_file('Same-2.0.tca')
        self.db.stage_app_update(app_id, new_file, 1, '2.0')
        self.assertTrue(self.db.approve_app(app_id, self.moderator))
        self.assertEqual(self.db.get_app(app_id)['file_path'], new_file)

    def test_only_a_moderator_approves(self):
        app_id = self.a_package('Guarded')
        self.db.stage_app_update(app_id, self.a_file('Guarded-2.tca'), 1, '2.0')
        self.assertFalse(self.db.approve_app(app_id, self.author))
        self.assertEqual(self.db.get_app(app_id)['version'], '1.0')

    def test_rejecting_throws_the_update_away_and_leaves_the_package(self):
        app_id = self.a_package('Kept')
        new_file = self.a_file('Kept-2.0.tca')
        self.db.stage_app_update(app_id, new_file, 1, '2.0')
        refused = self.db.reject_app_update(app_id, self.author)
        self.assertFalse(refused['success'])
        result = self.db.reject_app_update(app_id, self.moderator)
        self.assertTrue(result['success'])
        self.assertEqual(result['old_file'], new_file)
        row = self.db.get_app(app_id)
        self.assertEqual(row['approved'], 1)
        self.assertEqual(row['version'], '1.0')
        self.assertIsNone(row['update_file_path'])
        self.assertFalse(self.db.reject_app_update(app_id, self.moderator)['success'],
                         'nothing is waiting any more')

    def test_the_details_change_at_once(self):
        app_id = self.a_package('Renamed')
        self.assertTrue(self.db.update_app_metadata(app_id, name='Renamed 2', description='Better'))
        row = self.db.get_app(app_id)
        self.assertEqual(row['name'], 'Renamed 2')
        self.assertEqual(row['description'], 'Better')
        self.assertEqual(row['category'], 'application', 'None leaves a field alone')
        self.assertTrue(self.db.update_app_metadata(app_id), 'nothing to change is not a failure')

    def test_the_pending_list_carries_updates_flagged(self):
        fresh = self.a_package('Fresh', approved=False)
        listed = self.a_package('Listed')
        self.db.stage_app_update(listed, self.a_file('Listed-3.tca'), 1, '3.0')
        pending = {app['id']: app for app in self.db.get_pending_apps()}
        self.assertIn(fresh, pending)
        self.assertIn(listed, pending)
        self.assertFalse(pending[fresh]['pending_update'])
        self.assertTrue(pending[listed]['pending_update'])
        self.assertEqual(pending[listed]['update_version'], '3.0')
        self.assertEqual(pending[listed]['version'], '1.0')
        for app in pending.values():
            self.assertNotIn('file_path', app)
            self.assertNotIn('update_file_path', app)

    def test_whats_new_calls_an_updated_package_an_update(self):
        app_id = self.a_package('News')
        self.db.stage_app_update(app_id, self.a_file('News-2.tca'), 1, '2.0')
        self.db.approve_app(app_id, self.moderator)
        news = self.db.get_whats_new(self.reviewer)
        self.assertIn(app_id, [a['id'] for a in news['app_updates_items']])
        self.assertNotIn(app_id, [a['id'] for a in news['new_apps_items']])


class ARatingIsGivenOnce(RepositoryCase):

    def test_a_review_is_kept_and_counted(self):
        app_id = self.a_package('Rated')
        result = self.db.add_app_review(app_id, self.reviewer, 4, 'Good enough')
        self.assertTrue(result['success'], result)
        reviews = self.db.get_app_reviews(app_id)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]['username'], 'reviewer')
        self.assertEqual(reviews[0]['rating'], 4)
        self.assertEqual(reviews[0]['review'], 'Good enough')
        rating = self.db.get_app_rating(app_id)
        self.assertEqual(rating, {'rating_average': 4.0, 'rating_count': 1})
        self.assertEqual(self.db.get_user_app_review(app_id, self.reviewer)['rating'], 4)
        self.assertIsNone(self.db.get_user_app_review(app_id, self.other))

    def test_the_average_is_carried_by_every_listing(self):
        app_id = self.a_package('Averaged')
        self.db.add_app_review(app_id, self.reviewer, 5)
        self.db.add_app_review(app_id, self.other, 4)
        listed = {a['id']: a for a in self.db.get_approved_apps()}[app_id]
        self.assertEqual(listed['rating_average'], 4.5)
        self.assertEqual(listed['rating_count'], 2)
        self.assertNotIn('file_path', listed)
        found = {a['id']: a for a in self.db.search_apps('Averaged')}[app_id]
        self.assertEqual(found['rating_count'], 2)
        self.assertEqual(self.db.get_app(app_id)['rating_average'], 4.5)

    def test_a_second_review_is_refused(self):
        app_id = self.a_package('Once')
        self.assertTrue(self.db.add_app_review(app_id, self.reviewer, 3)['success'])
        again = self.db.add_app_review(app_id, self.reviewer, 5, 'changed my mind')
        self.assertFalse(again['success'])
        self.assertTrue(again.get('already_reviewed'))
        self.assertEqual(self.db.get_app_rating(app_id)['rating_count'], 1)
        self.assertEqual(self.db.get_user_app_review(app_id, self.reviewer)['rating'], 3)

    def test_after_an_update_the_package_may_be_rated_again(self):
        """Once per RELEASE: the first review stands, marked with the
        version it was about, and the new release starts its own count."""
        app_id = self.a_package('Released')
        first = self.db.add_app_review(app_id, self.reviewer, 2, 'Rough')
        self.assertTrue(first['success'])
        self.assertFalse(self.db.add_app_review(app_id, self.reviewer, 5)['success'],
                         'not twice for one release')

        # The author ships version 2.0 and a moderator approves it.
        import time
        time.sleep(0.01)
        self.db.stage_app_update(app_id, self.a_file('Released-2.tca'), 1, '2.0')
        self.assertTrue(self.db.approve_app(app_id, self.moderator))

        self.assertIsNone(self.db.get_user_app_review(app_id, self.reviewer),
                          'the old review is about a release since replaced')
        self.assertEqual(self.db.get_app_rating(app_id), {'rating_average': None, 'rating_count': 0},
                         'the new release starts with no rating')
        listed = {a['id']: a for a in self.db.get_approved_apps()}[app_id]
        self.assertEqual(listed['rating_count'], 0)

        second = self.db.add_app_review(app_id, self.reviewer, 5, 'Much better')
        self.assertTrue(second['success'], second)
        self.assertFalse(self.db.add_app_review(app_id, self.reviewer, 4)['success'],
                         'and once for the new release too')

        reviews = self.db.get_app_reviews(app_id)
        self.assertEqual([(r['rating'], r['version'], r['current']) for r in reviews],
                         [(5, '2.0', 1), (2, '1.0', 0)])
        self.assertEqual(self.db.get_app_rating(app_id), {'rating_average': 5.0, 'rating_count': 1})
        self.assertEqual(self.db.get_user_app_review(app_id, self.reviewer)['rating'], 5)

    def test_a_change_of_the_details_alone_is_not_a_new_release(self):
        app_id = self.a_package('Retitled')
        self.assertTrue(self.db.add_app_review(app_id, self.reviewer, 4)['success'])
        self.db.update_app_metadata(app_id, name='Retitled again', version='1.0.1')
        self.assertFalse(self.db.add_app_review(app_id, self.reviewer, 5)['success'])
        self.assertEqual(self.db.get_app_rating(app_id)['rating_count'], 1)

    def test_the_first_shape_of_the_table_is_rebuilt(self):
        """A database made before reviews were per release has
        UNIQUE(app_id, user_id) and no version; opening it keeps every
        review and lets a user rate the next release."""
        import sqlite3
        tmp = tempfile.mkdtemp(prefix='titan-repo-migrate-')
        path = os.path.join(tmp, 'old.db')
        try:
            db = models.Database(path)
            db.create_user('root', 'password123', 'Root')
            author = db.create_user('author2', 'password123', 'A')['user_id']
            fan = db.create_user('fan', 'password123', 'F')['user_id']
            mod = db.create_user('mod2', 'password123', 'M')['user_id']
            db.set_user_role(mod, 'moderator')
            f = os.path.join(tmp, 'p.tca')
            open(f, 'wb').write(b'x')
            app_id = db.add_app_to_repository('Old', 'd', 'application', '1.0', author, f, 1, {})
            db.approve_app(app_id, mod)
            _close(db)
            # The Database is a singleton per path; forget this one so the
            # file is really opened again, migrations and all.
            models._LIVE_INSTANCES.pop(os.path.abspath(path), None)

            raw = sqlite3.connect(path)
            raw.executescript("""
                DROP TABLE IF EXISTS app_reviews;
                CREATE TABLE app_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                    rating INTEGER NOT NULL, review TEXT, created_at TEXT NOT NULL,
                    UNIQUE(app_id, user_id));
            """)
            raw.execute("INSERT INTO app_reviews (app_id, user_id, rating, review, created_at) VALUES (?, ?, 3, 'old words', '2026-01-01T00:00:00')",
                        (app_id, fan))
            raw.commit()
            raw.close()

            reopened = models.Database(path)
            try:
                rows = reopened.get_app_reviews(app_id)
                self.assertEqual([(r['rating'], r['review'], r['version']) for r in rows],
                                 [(3, 'old words', '1.0')])
                self.assertFalse(reopened.add_app_review(app_id, fan, 5)['success'])
                reopened.stage_app_update(app_id, f, 1, '2.0')
                reopened.approve_app(app_id, mod)
                self.assertTrue(reopened.add_app_review(app_id, fan, 5)['success'],
                                'the constraint that said "for ever" is gone')
            finally:
                _close(reopened)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_author_may_not_rate_their_own(self):
        app_id = self.a_package('Mine')
        result = self.db.add_app_review(app_id, self.author, 5)
        self.assertFalse(result['success'])
        self.assertIn('own', result['error'])

    def test_a_package_nobody_approved_cannot_be_rated(self):
        app_id = self.a_package('Unseen', approved=False)
        self.assertFalse(self.db.add_app_review(app_id, self.reviewer, 5)['success'])

    def test_the_rating_is_one_to_five(self):
        app_id = self.a_package('Range')
        for bad in (0, 6, -1, 'five', None):
            self.assertFalse(self.db.add_app_review(app_id, self.reviewer, bad)['success'], bad)
        self.assertTrue(self.db.add_app_review(app_id, self.reviewer, '5')['success'],
                        'a number that arrived as text is a number')

    def test_a_review_that_is_too_long_is_refused(self):
        app_id = self.a_package('Long')
        self.assertFalse(self.db.add_app_review(app_id, self.reviewer, 5, 'x' * 4001)['success'])

    def test_a_review_is_deleted_by_its_author_or_a_moderator(self):
        app_id = self.a_package('Deleted')
        mine = self.db.add_app_review(app_id, self.reviewer, 2, 'meh')['review_id']
        theirs = self.db.add_app_review(app_id, self.other, 5, 'great')['review_id']
        self.assertFalse(self.db.delete_app_review(theirs, self.reviewer), 'not yours')
        self.assertTrue(self.db.delete_app_review(mine, self.reviewer), 'yours')
        self.assertTrue(self.db.delete_app_review(theirs, self.moderator), 'a moderator')
        self.assertFalse(self.db.delete_app_review(theirs, self.moderator), 'already gone')
        self.assertEqual(self.db.get_app_rating(app_id)['rating_count'], 0)

    def test_public_app_hides_the_paths_and_says_what_is_waiting(self):
        row = {'id': 1, 'file_path': '/secret', 'update_file_path': '/secret2',
               'update_version': '2.0', 'update_file_size': 3, 'update_uploaded_at': 'now'}
        public = models.Database.public_app(row)
        self.assertNotIn('file_path', public)
        self.assertNotIn('update_file_path', public)
        self.assertTrue(public['pending_update'])
        self.assertEqual(public['update_version'], '2.0')
        quiet = models.Database.public_app({'id': 2, 'file_path': '/x', 'update_file_path': None,
                                            'update_version': None})
        self.assertFalse(quiet['pending_update'])
        self.assertNotIn('update_version', quiet)
        self.assertIsNone(models.Database.public_app(None))


class OverHttp(RepositoryCase):
    """The routes, driven through aiohttp's test client."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import http_server
        import auth_tokens
        cls.uploads = os.path.join(cls.tmp, 'uploads')
        cls.server = http_server.TitanNetHTTPServer(
            host='127.0.0.1', port=0, upload_dir=cls.uploads, db=cls.db)
        cls.tokens = {
            cls.author: auth_tokens.mint(cls.author, 'author', 'user'),
            cls.reviewer: auth_tokens.mint(cls.reviewer, 'reviewer', 'user'),
            cls.other: auth_tokens.mint(cls.other, 'other', 'user'),
            cls.moderator: auth_tokens.mint(cls.moderator, 'mod', 'moderator'),
        }
        # One loop and one client for the whole class: an aiohttp
        # Application binds itself to the first loop that serves it.
        from aiohttp.test_utils import TestClient, TestServer
        cls.loop = asyncio.new_event_loop()
        cls.client = TestClient(TestServer(cls.server.app), loop=cls.loop)
        cls.loop.run_until_complete(cls.client.start_server())

    @classmethod
    def tearDownClass(cls):
        try:
            cls.loop.run_until_complete(cls.client.close())
        finally:
            cls.loop.close()
        super().tearDownClass()

    def run_async(self, coro):
        return self.loop.run_until_complete(coro)

    def headers(self, user):
        return {'Authorization': 'Bearer ' + self.tokens[user]}

    async def _request(self, method, path, user=None, **kwargs):
        headers = self.headers(user) if user else {}
        async with self.client.request(method, path, headers=headers, **kwargs) as resp:
            try:
                data = await resp.json()
            except Exception:
                data = None
            return resp.status, data

    def call(self, method, path, user=None, **kwargs):
        return self.run_async(self._request(method, path, user, **kwargs))

    def package_form(self, metadata, filename=None, content=b'a new package'):
        import aiohttp
        form = aiohttp.FormData()
        form.add_field('metadata', json.dumps(metadata), content_type='application/json')
        if filename:
            form.add_field('file', content, filename=filename, content_type='application/octet-stream')
        return form

    # ---- updating -------------------------------------------------------

    def test_the_author_stages_a_new_file(self):
        app_id = self.a_package('HttpUpdate')
        listed_file = self.db.get_app(app_id)['file_path']
        status, data = self.call(
            'POST', f'/api/repository/apps/{app_id}/update', self.author,
            data=self.package_form({'version': '2.0', 'description': 'Now better'}, 'thing.tca'))
        self.assertEqual(status, 200, data)
        self.assertTrue(data['success'])
        self.assertTrue(data['pending_update'])
        row = self.db.get_app(app_id)
        self.assertEqual(row['file_path'], listed_file, 'still the listed file')
        self.assertEqual(row['description'], 'Now better', 'the details changed at once')
        self.assertEqual(row['update_version'], '2.0')
        self.assertTrue(row['update_file_path'].startswith(os.path.join(self.uploads, 'pending')))
        self.assertTrue(os.path.exists(row['update_file_path']))
        self.assertTrue(row['update_file_path'].endswith('.tca'))

    def test_a_stranger_may_not(self):
        app_id = self.a_package('NotYours')
        status, data = self.call(
            'POST', f'/api/repository/apps/{app_id}/update', self.other,
            data=self.package_form({'name': 'Stolen'}))
        self.assertEqual(status, 403)
        self.assertEqual(self.db.get_app(app_id)['name'], 'NotYours')
        status, _data = self.call('POST', f'/api/repository/apps/{app_id}/update',
                                  data=self.package_form({'name': 'Anon'}))
        self.assertEqual(status, 401)

    def test_only_the_author_updates_even_a_moderator_may_not(self):
        """A moderator reviews and may remove a package; a new version of
        somebody else's work is that person's to send."""
        app_id = self.a_package('Moderated')
        status, data = self.call(
            'POST', f'/api/repository/apps/{app_id}/update', self.moderator,
            data=self.package_form({'name': 'Moderated, fixed'}))
        self.assertEqual(status, 403, data)
        self.assertIn('author', data['error'])
        self.assertEqual(self.db.get_app(app_id)['name'], 'Moderated')
        status, data = self.call(
            'POST', f'/api/repository/apps/{app_id}/update', self.moderator,
            data=self.package_form({'version': '9.0'}, 'thing.tca'))
        self.assertEqual(status, 403)
        self.assertIsNone(self.db.get_app(app_id)['update_file_path'])
        # Deleting is still theirs.
        status, data = self.call('DELETE', f'/api/repository/apps/{app_id}', self.moderator)
        self.assertEqual(status, 200, data)

    def test_the_details_alone_change_at_once(self):
        app_id = self.a_package('DetailsOnly')
        status, data = self.call(
            'POST', f'/api/repository/apps/{app_id}/update', self.author,
            data=self.package_form({'name': 'New name', 'version': '1.0.1'}))
        self.assertEqual(status, 200, data)
        self.assertFalse(data['pending_update'])
        row = self.db.get_app(app_id)
        self.assertEqual(row['name'], 'New name')
        self.assertEqual(row['version'], '1.0.1')
        self.assertIsNone(row['update_file_path'])

    def test_an_empty_update_and_a_bad_category_are_refused(self):
        app_id = self.a_package('Empty')
        status, data = self.call('POST', f'/api/repository/apps/{app_id}/update', self.author,
                                 data=self.package_form({}))
        self.assertEqual(status, 400)
        status, data = self.call('POST', f'/api/repository/apps/{app_id}/update', self.author,
                                 data=self.package_form({'category': 'malware'}))
        self.assertEqual(status, 400)
        status, data = self.call('POST', f'/api/repository/apps/{app_id}/update', self.author,
                                 data=self.package_form({'name': '   '}))
        self.assertEqual(status, 400)
        status, data = self.call('POST', f'/api/repository/apps/{app_id}/update', self.author,
                                 data=self.package_form({'version': '2.0'}, 'evil.exe'))
        self.assertEqual(status, 400)
        self.assertIsNone(self.db.get_app(app_id)['update_file_path'])

    def test_a_missing_package_is_404(self):
        status, _data = self.call('POST', '/api/repository/apps/999999/update', self.author,
                                  data=self.package_form({'name': 'x'}))
        self.assertEqual(status, 404)

    def test_approving_moves_the_file_and_removes_the_old_one(self):
        app_id = self.a_package('Approved')
        self.call('POST', f'/api/repository/apps/{app_id}/update', self.author,
                  data=self.package_form({'version': '2.0'}, 'thing.tca', b'version two'))
        before = self.db.get_app(app_id)
        old_file, staged = before['file_path'], before['update_file_path']
        self.assertTrue(os.path.exists(old_file) and os.path.exists(staged))

        status, data = self.call('POST', f'/api/repository/apps/{app_id}/approve', self.moderator)
        self.assertEqual(status, 200, data)
        self.assertTrue(data.get('update'))
        row = self.db.get_app(app_id)
        self.assertEqual(row['version'], '2.0')
        self.assertTrue(row['file_path'].startswith(os.path.join(self.uploads, 'approved')))
        self.assertTrue(os.path.exists(row['file_path']))
        with open(row['file_path'], 'rb') as fh:
            self.assertEqual(fh.read(), b'version two')
        self.assertFalse(os.path.exists(old_file), 'the replaced file is gone')
        self.assertFalse(os.path.exists(staged), 'and the staged one was moved')
        # And downloading answers the new file under the new version.
        status, _data = self.call('GET', f'/api/download/{app_id}')
        self.assertEqual(status, 200)

    def test_the_legacy_approve_route_does_the_same(self):
        app_id = self.a_package('LegacyApproved')
        self.call('POST', f'/api/repository/apps/{app_id}/update', self.author,
                  data=self.package_form({'version': '2.0'}, 'thing.tca', b'two'))
        # /api/approve wants an admin; a moderator role is not is_admin, so
        # make the moderator one for this route.
        conn = self.db.get_connection()
        cols = [c['name'] for c in conn.cursor().execute("PRAGMA table_info(users)").fetchall()]
        conn.close()
        if 'is_admin' not in cols:
            self.skipTest('no is_admin column on users')

        def make_admin():
            conn = self.db.get_connection()
            conn.cursor().execute("UPDATE users SET is_admin = 1 WHERE id = ?", (self.moderator,))
            conn.commit()
            conn.close()
        self.db.run_write(make_admin).result(timeout=10)
        status, data = self.call('POST', f'/api/approve/{app_id}', self.moderator)
        self.assertEqual(status, 200, data)
        self.assertEqual(self.db.get_app(app_id)['version'], '2.0')

    def test_rejecting_keeps_the_package_and_removes_the_staged_file(self):
        app_id = self.a_package('Rejected')
        self.call('POST', f'/api/repository/apps/{app_id}/update', self.author,
                  data=self.package_form({'version': '2.0'}, 'thing.tca'))
        staged = self.db.get_app(app_id)['update_file_path']
        status, data = self.call('POST', f'/api/repository/apps/{app_id}/reject', self.author)
        self.assertEqual(status, 403, 'the author may not moderate their own update')
        status, data = self.call('POST', f'/api/repository/apps/{app_id}/reject', self.moderator)
        self.assertEqual(status, 200, data)
        self.assertTrue(data.get('update'))
        row = self.db.get_app(app_id)
        self.assertEqual(row['approved'], 1)
        self.assertEqual(row['version'], '1.0')
        self.assertIsNone(row['update_file_path'])
        self.assertFalse(os.path.exists(staged))

    def test_the_pending_list_is_reachable_and_marks_updates(self):
        app_id = self.a_package('PendingListed')
        self.call('POST', f'/api/repository/apps/{app_id}/update', self.author,
                  data=self.package_form({'version': '2.0'}, 'thing.tca'))
        # The named route, which the {app_id} route used to swallow.
        status, data = self.call('GET', '/api/repository/apps/pending', self.moderator)
        self.assertEqual(status, 200, data)
        mine = [a for a in data['apps'] if a['id'] == app_id]
        self.assertEqual(len(mine), 1)
        self.assertTrue(mine[0]['pending_update'])
        self.assertNotIn('update_file_path', mine[0])
        # And the filtered listing the desktop client uses.
        status, data = self.call('GET', '/api/repository/apps?status=pending')
        self.assertEqual(status, 200)
        self.assertIn(app_id, [a['id'] for a in data['apps']])
        for app in data['apps']:
            self.assertNotIn('file_path', app)
            self.assertNotIn('update_file_path', app)

    def test_delete_answers_at_the_address_the_client_sends(self):
        app_id = self.a_package('Deleted')
        path = self.db.get_app(app_id)['file_path']
        status, data = self.call('DELETE', f'/api/repository/apps/{app_id}', self.other)
        self.assertEqual(status, 403)
        status, data = self.call('DELETE', f'/api/repository/apps/{app_id}', self.author)
        self.assertEqual(status, 200, data)
        self.assertIsNone(self.db.get_app(app_id))
        self.assertFalse(os.path.exists(path))

    # ---- reviews --------------------------------------------------------

    def test_details_say_the_rating_and_what_this_user_may_do(self):
        app_id = self.a_package('Detailed')
        self.db.add_app_review(app_id, self.other, 3, 'fine')
        status, data = self.call('GET', f'/api/repository/apps/{app_id}')
        self.assertEqual(status, 200)
        app = data['app']
        self.assertEqual(app['rating_average'], 3.0)
        self.assertEqual(app['rating_count'], 1)
        self.assertFalse(app['can_review'], 'nobody signed in')
        self.assertEqual(app['review_refusal'], 'not_signed_in', 'and it says so')
        self.assertFalse(app['can_manage'])
        self.assertFalse(app['can_update'])
        self.assertNotIn('file_path', app)
        self.assertNotIn('update_file_path', app)

        status, data = self.call('GET', f'/api/repository/apps/{app_id}', self.reviewer)
        self.assertTrue(data['app']['can_review'])
        self.assertIsNone(data['app']['review_refusal'], 'nothing stops them')
        self.assertFalse(data['app']['can_manage'])
        self.assertFalse(data['app']['can_update'])
        self.assertIsNone(data['app']['my_review'])

        status, data = self.call('GET', f'/api/repository/apps/{app_id}', self.other)
        self.assertFalse(data['app']['can_review'], 'already did')
        self.assertEqual(data['app']['review_refusal'], 'already_reviewed')
        self.assertEqual(data['app']['my_review']['rating'], 3)

        status, data = self.call('GET', f'/api/repository/apps/{app_id}', self.author)
        self.assertFalse(data['app']['can_review'], 'their own')
        self.assertEqual(data['app']['review_refusal'], 'own_package',
                         'the commonest refusal on a small server, and it is named')
        self.assertTrue(data['app']['can_manage'])
        self.assertTrue(data['app']['can_update'], 'only the author updates')

        status, data = self.call('GET', f'/api/repository/apps/{app_id}', self.moderator)
        self.assertTrue(data['app']['can_manage'], 'a moderator may delete')
        self.assertFalse(data['app']['can_update'], 'but not update')

    def test_a_review_is_sent_once(self):
        app_id = self.a_package('Reviewed')
        status, data = self.call('POST', f'/api/repository/apps/{app_id}/reviews', self.reviewer,
                                 json={'rating': 5, 'review': 'Splendid'})
        self.assertEqual(status, 200, data)
        self.assertEqual(data['rating_average'], 5.0)
        self.assertEqual(data['rating_count'], 1)

        status, data = self.call('POST', f'/api/repository/apps/{app_id}/reviews', self.reviewer,
                                 json={'rating': 1, 'review': 'Changed my mind'})
        self.assertEqual(status, 409, data)
        self.assertTrue(data.get('already_reviewed'))

        status, data = self.call('POST', f'/api/repository/apps/{app_id}/reviews', self.author,
                                 json={'rating': 5})
        self.assertEqual(status, 400, 'never one\'s own')

        status, data = self.call('POST', f'/api/repository/apps/{app_id}/reviews',
                                 json={'rating': 5})
        self.assertEqual(status, 401)

        status, data = self.call('POST', f'/api/repository/apps/{app_id}/reviews', self.other,
                                 json={'rating': 9})
        self.assertEqual(status, 400)

        status, data = self.call('POST', '/api/repository/apps/999999/reviews', self.other,
                                 json={'rating': 4})
        self.assertEqual(status, 404)

    def test_the_reviews_are_listed_with_the_summary(self):
        app_id = self.a_package('Listed reviews')
        self.db.add_app_review(app_id, self.reviewer, 4, 'Good')
        self.db.add_app_review(app_id, self.other, 2, '')
        status, data = self.call('GET', f'/api/repository/apps/{app_id}/reviews')
        self.assertEqual(status, 200)
        self.assertEqual(data['rating_count'], 2)
        self.assertEqual(data['rating_average'], 3.0)
        self.assertEqual({r['username'] for r in data['reviews']}, {'reviewer', 'other'})
        self.assertFalse(data['can_review'])
        self.assertEqual(data['review_refusal'], 'not_signed_in')
        self.assertIsNone(data['my_review'])
        status, data = self.call('GET', f'/api/repository/apps/{app_id}/reviews', self.reviewer)
        self.assertEqual(data['my_review']['rating'], 4)
        self.assertFalse(data['can_review'])
        self.assertEqual(data['review_refusal'], 'already_reviewed')
        status, data = self.call('GET', f'/api/repository/apps/{app_id}/reviews', self.author)
        self.assertEqual(data['review_refusal'], 'own_package')
        status, data = self.call('GET', f'/api/repository/apps/{app_id}/reviews', self.moderator)
        self.assertTrue(data['can_review'], 'a moderator who has not rated may')
        self.assertIsNone(data['review_refusal'])

    def test_a_package_nobody_has_approved_says_so(self):
        app_id = self.a_package('Unapproved', approved=False)
        status, data = self.call('GET', f'/api/repository/apps/{app_id}/reviews', self.reviewer)
        self.assertEqual(status, 200)
        self.assertFalse(data['can_review'])
        self.assertEqual(data['review_refusal'], 'not_approved')

    def test_a_review_is_deleted_by_its_author_or_a_moderator(self):
        app_id = self.a_package('Review deletion')
        review_id = self.db.add_app_review(app_id, self.reviewer, 4, 'Good')['review_id']
        status, _data = self.call('DELETE', f'/api/repository/reviews/{review_id}', self.other)
        self.assertEqual(status, 403)
        status, _data = self.call('DELETE', f'/api/repository/reviews/{review_id}', self.moderator)
        self.assertEqual(status, 200)
        self.assertEqual(self.db.get_app_reviews(app_id), [])

    def test_the_listing_carries_the_rating(self):
        app_id = self.a_package('Listed rating')
        self.db.add_app_review(app_id, self.reviewer, 5)
        status, data = self.call('GET', '/api/repository/apps?status=approved')
        self.assertEqual(status, 200)
        mine = [a for a in data['apps'] if a['id'] == app_id][0]
        self.assertEqual(mine['rating_average'], 5.0)
        self.assertEqual(mine['rating_count'], 1)
        status, data = self.call('GET', '/api/search?q=Listed%20rating')
        mine = [a for a in data['apps'] if a['id'] == app_id][0]
        self.assertEqual(mine['rating_count'], 1)
        self.assertNotIn('file_path', mine)


if __name__ == '__main__':
    unittest.main(verbosity=2)
