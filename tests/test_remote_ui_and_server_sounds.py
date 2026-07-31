# -*- coding: utf-8 -*-
"""
Tests for the two Titan-Net features that let the SERVER extend the client:

1. Remote UI - the server describes a dialog as JSON and every client renders
   it, so a new Titan-Net screen never requires users to update Titan.
2. Server sounds - audio the server can play at one user, a role, a room or
   everybody, cached on the client by content hash.

The important property under test is that the two halves stay in step: the
field types the server will accept must all be types the client renderer
knows how to draw, and a value the client sends must survive the server's
own validation. Drift between them is exactly the bug that would strand a
screen half-drawn on somebody's machine.
"""

import asyncio
import hashlib
import importlib.util
import json
import os
import sys
import types
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SERVER_DIR = os.path.join(REPO, 'titan-net server')
# Server modules import each other by bare name ('from models import ...'),
# so the server directory has to be importable in its own right.
sys.path.insert(0, SERVER_DIR)


def _load_server_module(name: str):
    """Import a module out of 'titan-net server' (the space blocks import)."""
    path = os.path.join(SERVER_DIR, f'{name}.py')
    spec = importlib.util.spec_from_file_location(f'_srv_{name}', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


server_remote_ui = _load_server_module('remote_ui')


# ---------------------------------------------------------------------------
# Screen definitions
# ---------------------------------------------------------------------------

class DefinitionValidationTest(unittest.TestCase):

    def test_a_minimal_screen_is_accepted_and_gets_a_close_button(self):
        ok, why, screen = server_remote_ui.validate_definition({'title': 'Hello'})
        self.assertTrue(ok, why)
        self.assertEqual(screen['title'], 'Hello')
        # A screen with no buttons would trap the user; one is supplied.
        self.assertTrue(screen['buttons'])
        self.assertEqual(screen['buttons'][0]['action'], 'cancel')

    def test_a_screen_without_a_title_is_rejected(self):
        ok, why, _screen = server_remote_ui.validate_definition({'fields': []})
        self.assertFalse(ok)
        self.assertIn('title', why.lower())

    def test_json_text_is_accepted_as_well_as_a_dict(self):
        ok, _why, screen = server_remote_ui.validate_definition(
            json.dumps({'title': 'From text'}))
        self.assertTrue(ok)
        self.assertEqual(screen['title'], 'From text')

    def test_unknown_field_type_is_refused_at_save_time(self):
        ok, why, _screen = server_remote_ui.validate_definition({
            'title': 'x',
            'fields': [{'type': 'webview', 'id': 'w'}],
        })
        self.assertFalse(ok, "a field type no client can draw was accepted")
        self.assertIn('webview', why)

    def test_duplicate_field_ids_are_refused(self):
        ok, why, _screen = server_remote_ui.validate_definition({
            'title': 'x',
            'fields': [{'type': 'text', 'id': 'a'}, {'type': 'text', 'id': 'a'}],
        })
        self.assertFalse(ok)
        self.assertIn('Duplicate', why)

    def test_items_shorthand_is_expanded_for_the_client(self):
        _ok, _why, screen = server_remote_ui.validate_definition({
            'title': 'x',
            'fields': [{'type': 'choice', 'id': 'c', 'items': ['one', 'two']}],
        })
        self.assertEqual(screen['fields'][0]['items'],
                         [{'value': 'one', 'label': 'one'},
                          {'value': 'two', 'label': 'two'}])

    def test_number_default_is_clamped_into_range(self):
        _ok, _why, screen = server_remote_ui.validate_definition({
            'title': 'x',
            'fields': [{'type': 'number', 'id': 'n', 'min': 5, 'max': 9, 'default': 99}],
        })
        self.assertEqual(screen['fields'][0]['default'], 9)

    def test_inverted_number_range_is_refused(self):
        ok, why, _screen = server_remote_ui.validate_definition({
            'title': 'x',
            'fields': [{'type': 'number', 'id': 'n', 'min': 10, 'max': 2}],
        })
        self.assertFalse(ok)
        self.assertIn('min', why)

    def test_an_open_button_must_name_a_screen(self):
        ok, why, _screen = server_remote_ui.validate_definition({
            'title': 'x',
            'buttons': [{'id': 'go', 'action': 'open'}],
        })
        self.assertFalse(ok)
        self.assertIn('opens nothing', why)

    def test_field_count_is_bounded(self):
        ok, why, _screen = server_remote_ui.validate_definition({
            'title': 'x',
            'fields': [{'type': 'text', 'id': f'f{i}'}
                       for i in range(server_remote_ui.MAX_FIELDS + 1)],
        })
        self.assertFalse(ok)
        self.assertIn('Too many fields', why)


class ServiceViewTest(unittest.TestCase):
    """A 'view' screen is how a whole SERVICE is described to the client."""

    def _view(self, **extra):
        definition = {'kind': 'view', 'title': 'Service',
                      'items': [{'id': 'a', 'label': 'Row A', 'action': 'read'}]}
        definition.update(extra)
        return server_remote_ui.validate_definition(definition)

    def test_a_view_is_accepted_and_keeps_its_kind(self):
        ok, why, screen = self._view()
        self.assertTrue(ok, why)
        self.assertEqual(screen['kind'], 'view')

    def test_a_view_needs_no_button_bar(self):
        """Escape means back in a view, so no Close button is invented."""
        _ok, _why, screen = self._view()
        self.assertEqual(screen['buttons'], [])

    def test_a_form_still_gets_a_close_button(self):
        _ok, _why, screen = server_remote_ui.validate_definition({'title': 'Form'})
        self.assertTrue(screen['buttons'])

    def test_plain_strings_are_accepted_as_rows(self):
        _ok, _why, screen = self._view(items=['One', 'Two'])
        self.assertEqual([r['label'] for r in screen['items']], ['One', 'Two'])
        self.assertEqual(screen['items'][0]['action'], 'activate')

    def test_a_row_without_a_label_is_refused(self):
        ok, why, _screen = self._view(items=[{'action': 'read'}])
        self.assertFalse(ok)
        self.assertIn('label', why)

    def test_row_count_is_bounded(self):
        ok, why, _screen = self._view(
            items=[{'id': str(i), 'label': str(i)}
                   for i in range(server_remote_ui.MAX_VIEW_ROWS + 1)])
        self.assertFalse(ok)
        self.assertIn('Too many rows', why)

    def test_tabs_are_normalised_and_the_active_one_is_valid(self):
        _ok, _why, screen = self._view(
            tabs=['live', {'id': 'archive', 'label': 'Archive'}],
            active_tab='archive')
        self.assertEqual([t['id'] for t in screen['tabs']], ['live', 'archive'])
        self.assertEqual(screen['active_tab'], 'archive')

    def test_an_unknown_active_tab_falls_back_to_the_first(self):
        _ok, _why, screen = self._view(tabs=['a', 'b'], active_tab='nope')
        self.assertEqual(screen['active_tab'], 'a')

    def test_menus_accept_separators_and_reject_unknown_actions(self):
        _ok, _why, screen = self._view(menus=[{'label': 'File', 'items': [
            {'id': 'x', 'label': 'Do it'}, '-',
            {'id': 'q', 'label': 'Close', 'action': 'close'}]}])
        self.assertEqual(len(screen['menus'][0]['items']), 3)
        self.assertTrue(screen['menus'][0]['items'][1]['separator'])

        ok, why, _screen = self._view(menus=[{'label': 'File', 'items': [
            {'id': 'x', 'label': 'Do it', 'action': 'launch_rocket'}]}])
        self.assertFalse(ok)
        self.assertIn('launch_rocket', why)

    def test_a_menu_item_that_opens_nothing_is_refused(self):
        ok, why, _screen = self._view(menus=[{'label': 'File', 'items': [
            {'id': 'x', 'label': 'Go', 'action': 'open'}]}])
        self.assertFalse(ok)
        self.assertIn('opens nothing', why)

    def test_auto_refresh_is_clamped_to_something_sane(self):
        _ok, _why, screen = self._view(refresh_seconds=1)
        self.assertGreaterEqual(screen['refresh_seconds'], 10)
        _ok, _why, screen = self._view(refresh_seconds=99999)
        self.assertLessEqual(screen['refresh_seconds'], 3600)

    def test_an_empty_view_explains_itself(self):
        _ok, _why, screen = self._view(items=[])
        self.assertTrue(screen['empty'],
                        "an empty service would read as a broken one")

    def test_only_rows_the_server_offered_can_be_fired(self):
        _ok, _why, screen = self._view()
        clean, errors = server_remote_ui.coerce_values(screen, {'item': 'a'})
        self.assertEqual(clean['item'], 'a')
        _clean, errors = server_remote_ui.coerce_values(screen, {'item': 'ghost'})
        self.assertIn('item', errors)

    def test_navigation_is_not_blocked_by_an_unfinished_form(self):
        """Firing a row must work even when a required control is empty."""
        _ok, _why, screen = self._view(
            fields=[{'type': 'text', 'id': 'q', 'required': True}])
        _clean, errors = server_remote_ui.coerce_values(
            screen, {'item': 'a', 'q': ''}, strict=True)
        self.assertIn('q', errors)
        clean, errors = server_remote_ui.coerce_values(
            screen, {'item': 'a', 'q': ''}, strict=False)
        self.assertEqual(errors, {})
        self.assertEqual(clean['item'], 'a')

    def test_a_missing_row_is_still_reported_when_not_strict(self):
        _ok, _why, screen = self._view()
        _clean, errors = server_remote_ui.coerce_values(
            screen, {'item': 'ghost'}, strict=False)
        self.assertIn('item', errors)

    def test_view_helper_builds_a_valid_screen(self):
        result = server_remote_ui.view('Radio', ['Channel 1'],
                                       status='On air', tabs=['live'])
        self.assertIn('screen', result)
        self.assertEqual(result['screen']['kind'], 'view')
        self.assertEqual(result['screen']['status'], 'On air')

    def test_refresh_helper_keeps_the_user_in_place(self):
        result = server_remote_ui.refresh(items=['a'], status='1 item')
        self.assertTrue(result['refresh'])
        self.assertNotIn('screen', result,
                         "refresh must not redraw the whole screen")

    def test_refresh_helper_rejects_rows_the_client_could_not_show(self):
        result = server_remote_ui.refresh(items=[{'nope': 1}])
        self.assertNotIn('items', result)
        self.assertIn('message', result)

    def test_context_resolves_the_fired_row(self):
        _ok, _why, screen = self._view(
            items=[{'id': 'a', 'label': 'A', 'data': {'x': 1}}])
        ctx = server_remote_ui.ScreenContext(
            None, types.SimpleNamespace(is_moderator=lambda uid: False),
            {'id': 1, 'username': 'ala'}, {'slug': 's'}, screen,
            'read', {'item': 'a'})
        self.assertEqual(ctx.item, 'a')
        self.assertEqual(ctx.row['data'], {'x': 1})

    def test_the_builtin_store_handler_ignores_navigation(self):
        """F5 and tab cycling must not be recorded as form submissions."""
        recorded = []
        db = types.SimpleNamespace(
            is_moderator=lambda uid: False,
            run_write=lambda *a, **kw: recorded.append(a))
        _ok, _why, screen = self._view()
        for action in ('refresh', 'tab', 'activate'):
            ctx = server_remote_ui.ScreenContext(
                None, db, {'id': 1, 'username': 'ala'}, {'slug': 's'},
                screen, action, {})
            result = asyncio.run(server_remote_ui.run_handler('store', ctx))
            self.assertIn('screen', result)
        self.assertEqual(recorded, [],
                         "navigation was written to the submissions log")


class ValueCoercionTest(unittest.TestCase):
    """The server, not the client, decides whether a submit is acceptable."""

    def setUp(self):
        _ok, _why, self.screen = server_remote_ui.validate_definition({
            'title': 'Form',
            'fields': [
                {'type': 'text', 'id': 'name', 'required': True, 'max_length': 10},
                {'type': 'number', 'id': 'age', 'min': 1, 'max': 120},
                {'type': 'choice', 'id': 'colour', 'items': ['red', 'blue']},
                {'type': 'checkbox', 'id': 'agree'},
                {'type': 'static', 'id': 'note', 'text': 'hi'},
            ],
        })

    def test_good_values_pass_through(self):
        clean, errors = server_remote_ui.coerce_values(
            self.screen, {'name': 'Ala', 'age': 30, 'colour': 'red', 'agree': True})
        self.assertEqual(errors, {})
        self.assertEqual(clean, {'name': 'Ala', 'age': 30,
                                 'colour': 'red', 'agree': True})

    def test_required_empty_and_out_of_range_are_reported_per_field(self):
        clean, errors = server_remote_ui.coerce_values(
            self.screen, {'name': '   ', 'age': 500, 'colour': 'green'})
        self.assertIn('name', errors)
        self.assertIn('age', errors)
        self.assertIn('colour', errors)
        self.assertNotIn('name', clean)

    def test_a_label_is_accepted_where_a_value_was_expected(self):
        """Clients that rebuilt a list locally send back the visible label."""
        _ok, _why, screen = server_remote_ui.validate_definition({
            'title': 'x',
            'fields': [{'type': 'choice', 'id': 'c',
                        'items': [{'value': 7, 'label': 'seven'}]}],
        })
        clean, errors = server_remote_ui.coerce_values(screen, {'c': 'seven'})
        self.assertEqual(errors, {})
        self.assertEqual(clean['c'], 7)

    def test_fields_the_screen_never_declared_are_dropped(self):
        clean, _errors = server_remote_ui.coerce_values(
            self.screen, {'name': 'Ala', 'is_admin': True})
        self.assertNotIn('is_admin', clean,
                         "a client could smuggle in a field the screen never had")

    def test_static_fields_produce_no_value(self):
        clean, _errors = server_remote_ui.coerce_values(self.screen, {'name': 'Ala'})
        self.assertNotIn('note', clean)

    def test_a_non_dict_payload_does_not_crash(self):
        clean, errors = server_remote_ui.coerce_values(self.screen, "not a dict")
        self.assertIn('name', errors)
        self.assertIsInstance(clean, dict)


class HandlerRegistryTest(unittest.TestCase):

    def _context(self, action='open', values=None, definition=None):
        definition = definition or {'title': 'x', 'fields': [], 'buttons': []}
        db = types.SimpleNamespace(is_moderator=lambda uid: False)
        return server_remote_ui.ScreenContext(
            server=None, db=db, user={'id': 1, 'username': 'ala'},
            screen={'slug': 'demo', 'handler': 'store'},
            definition=definition, action=action, values=values or {})

    def test_builtin_handlers_are_registered(self):
        self.assertIn('store', server_remote_ui.HANDLERS)
        self.assertIn('readonly', server_remote_ui.HANDLERS)

    def test_opening_a_store_screen_returns_the_definition(self):
        result = asyncio.run(server_remote_ui.run_handler('store', self._context()))
        self.assertIn('screen', result)

    def test_an_unknown_handler_falls_back_instead_of_breaking_the_screen(self):
        result = asyncio.run(
            server_remote_ui.run_handler('no_such_handler', self._context()))
        self.assertIn('screen', result)

    def test_async_and_sync_handlers_both_work(self):
        @server_remote_ui.handler('_test_sync')
        def _sync(ctx):
            return server_remote_ui.close(message='sync')

        @server_remote_ui.handler('_test_async')
        async def _async(ctx):
            return server_remote_ui.close(message='async')

        self.assertEqual(
            asyncio.run(server_remote_ui.run_handler('_test_sync', self._context()))['message'],
            'sync')
        self.assertEqual(
            asyncio.run(server_remote_ui.run_handler('_test_async', self._context()))['message'],
            'async')

    def test_a_handler_returning_junk_closes_rather_than_hanging(self):
        @server_remote_ui.handler('_test_junk')
        def _junk(ctx):
            return "not a result"

        result = asyncio.run(server_remote_ui.run_handler('_test_junk', self._context()))
        self.assertTrue(result.get('close'))

    def test_fill_injects_live_options_into_the_definition(self):
        definition = {'title': 'x',
                      'fields': [{'type': 'choice', 'id': 'user', 'items': []}],
                      'buttons': []}
        ctx = self._context(definition=definition)
        result = ctx.fill({'user': {'items': ['ala', 'ola'], 'default': 'ola'}})
        field = result['screen']['fields'][0]
        self.assertEqual([i['label'] for i in field['items']], ['ala', 'ola'])
        self.assertEqual(field['default'], 'ola')

    def test_goto_rejects_a_screen_the_client_could_not_render(self):
        result = server_remote_ui.goto({'fields': []})   # no title
        self.assertNotIn('screen', result)
        self.assertIn('message', result)


# ---------------------------------------------------------------------------
# Client / server agreement
# ---------------------------------------------------------------------------

class ClientServerSchemaTest(unittest.TestCase):
    """A screen the server accepts must be one the client can actually draw."""

    def _client_source(self):
        path = os.path.join(REPO, 'src', 'network', 'remote_ui.py')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def test_every_server_field_type_is_handled_by_the_renderer(self):
        source = self._client_source()
        start = source.index('def _build_field')
        body = source[start:source.index('\n    # --- interaction', start)]
        for ftype in server_remote_ui.FIELD_TYPES:
            self.assertIn(f"'{ftype}'", body,
                          f"the client renderer has no branch for '{ftype}'")

    def test_every_server_button_action_is_handled(self):
        source = self._client_source()
        start = source.index('def _on_button')
        body = source[start:start + 2500]
        for action in server_remote_ui.BUTTON_ACTIONS:
            self.assertIn(f"'{action}'", body,
                          f"the client has no branch for button action '{action}'")

    def test_schema_versions_match(self):
        from src.network import remote_ui as client_remote_ui
        self.assertEqual(client_remote_ui.SCHEMA_VERSION,
                         server_remote_ui.SCHEMA_VERSION)

    def test_client_normalises_item_shorthand_the_same_way(self):
        from src.network import remote_ui as client_remote_ui
        self.assertEqual(client_remote_ui._items_of({'items': ['a']}),
                         [{'value': 'a', 'label': 'a'}])
        self.assertEqual(
            client_remote_ui._items_of({'items': [{'value': 1, 'label': 'one'}]}),
            [{'value': 1, 'label': 'one'}])

    def test_the_client_can_render_every_screen_kind(self):
        source = self._client_source()
        start = source.index('def show_screen')
        body = source[start:start + 1400]
        for kind in server_remote_ui.SCREEN_KINDS:
            self.assertIn(f"'{kind}'", body,
                          f"no client renderer for screen kind '{kind}'")
        self.assertIn('RemoteServiceFrame', body)

    def test_the_service_window_renders_menus_tabs_rows_and_controls(self):
        source = self._client_source()
        start = source.index('class RemoteServiceFrame')
        body = source[start:source.index('def _announce_tab_bar', start)]
        for expected in ('_build_menu_bar', '_tab_bar_text', '_fill_list',
                         '_build_field', '_activate_row', '_cycle_tab',
                         '_arm_auto_refresh'):
            self.assertIn(expected, body,
                          f"the service window is missing {expected}")

    def test_back_action_ids_match_on_both_sides(self):
        from src.network import remote_ui as client_remote_ui
        with open(os.path.join(REPO, 'titan-net server', 'server.py'),
                  encoding='utf-8') as fh:
            server_source = fh.read()
        self.assertIn(f"REMOTE_UI_BACK_ACTION = '{client_remote_ui.BACK_ACTION}'",
                      server_source,
                      "client and server disagree on the back action id, so "
                      "the two navigation stacks would drift apart")

    def test_confirmation_dialogs_compare_against_id_yes(self):
        """The Feedback Hub bug must not be reintroduced in the new modules."""
        for relative in ('src/network/remote_ui.py',
                         'src/network/server_sounds_gui.py'):
            with open(os.path.join(REPO, relative), encoding='utf-8') as fh:
                source = fh.read()
            self.assertNotIn('== wx.YES', source, relative)
            if 'YES_NO' in source:
                self.assertIn('wx.ID_YES', source, relative)


# ---------------------------------------------------------------------------
# Server sounds
# ---------------------------------------------------------------------------

class ServerSoundCacheTest(unittest.TestCase):

    def setUp(self):
        from src.network import server_sounds
        self.module = server_sounds
        self.payload = b'RIFF____WAVEfmt ' + bytes(64)
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.addCleanup(self._remove_cached, self.digest)

    def _remove_cached(self, digest):
        try:
            path = self.module._cache_path(digest)
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

    def test_a_sound_is_cached_under_its_content_hash(self):
        path = self.module._store(self.digest, self.payload)
        self.assertIsNotNone(path)
        self.assertTrue(self.module.is_cached(self.digest))
        with open(path, 'rb') as fh:
            self.assertEqual(fh.read(), self.payload)

    def test_a_payload_that_does_not_match_its_hash_is_discarded(self):
        wrong = 'f' * 64
        self.addCleanup(self._remove_cached, wrong)
        self.assertIsNone(self.module._store(wrong, self.payload),
                          "audio that did not match its advertised hash was cached")
        self.assertFalse(self.module.is_cached(wrong))

    def test_an_oversized_payload_is_refused(self):
        huge = b'x' * (self.module.MAX_SOUND_BYTES + 1)
        digest = hashlib.sha256(huge).hexdigest()
        self.addCleanup(self._remove_cached, digest)
        self.assertIsNone(self.module._store(digest, huge))

    def test_an_empty_payload_is_refused(self):
        self.assertIsNone(self.module._store('a' * 64, b''))

    def test_cache_paths_cannot_escape_the_cache_directory(self):
        path = self.module._cache_path('../../evil')
        directory = self.module.get_cache_dir()
        self.assertEqual(os.path.dirname(os.path.abspath(path)),
                         os.path.abspath(directory))

    def test_nothing_is_played_when_the_user_turned_server_sounds_off(self):
        original = self.module.is_enabled
        self.module.is_enabled = lambda: False
        try:
            played = self.module.play(None, {'name': 'x', 'sha256': self.digest})
        finally:
            self.module.is_enabled = original
        self.assertFalse(played)

    def test_a_message_without_a_name_is_ignored(self):
        original = self.module.is_enabled
        self.module.is_enabled = lambda: True
        try:
            self.assertFalse(self.module.play(None, {'sha256': self.digest}))
        finally:
            self.module.is_enabled = original


class SoundTargetTest(unittest.TestCase):
    """Target resolution decides who hears a sound - it must not over-reach."""

    def setUp(self):
        server_module = _load_server_module('server')
        self.server = server_module.TitanNetServer.__new__(server_module.TitanNetServer)
        self.server.clients = {
            's1': {'user_id': 1, 'username': 'ala'},
            's2': {'user_id': 2, 'username': 'ola'},
            's3': {'user_id': 3, 'username': 'mod'},
        }
        self.server._room_websockets = {5: {1: None, 2: None}}
        self.server._sound_pushes = {}
        roles = {1: 'user', 2: 'user', 3: 'moderator'}
        self.server.db = types.SimpleNamespace(
            get_user_by_id=lambda uid: {'role': roles.get(uid, 'user')},
            is_moderator=lambda uid: roles.get(uid) == 'moderator')

    def test_all_reaches_every_session(self):
        self.assertEqual(sorted(self.server._sessions_for_target({'type': 'all'})),
                         ['s1', 's2', 's3'])

    def test_a_username_reaches_only_that_user(self):
        self.assertEqual(
            self.server._sessions_for_target({'type': 'user', 'username': 'ola'}),
            ['s2'])

    def test_username_matching_ignores_case(self):
        self.assertEqual(
            self.server._sessions_for_target({'type': 'user', 'username': 'OLA'}),
            ['s2'])

    def test_a_role_reaches_only_that_role(self):
        self.assertEqual(
            self.server._sessions_for_target({'type': 'role', 'role': 'moderator'}),
            ['s3'])

    def test_a_room_reaches_only_its_members(self):
        self.assertEqual(
            sorted(self.server._sessions_for_target({'type': 'room', 'room_id': 5})),
            ['s1', 's2'])

    def test_an_unknown_target_reaches_nobody(self):
        self.assertEqual(self.server._sessions_for_target({'type': 'planet'}), [])

    def test_a_missing_user_reaches_nobody(self):
        self.assertEqual(
            self.server._sessions_for_target({'type': 'user', 'username': 'ghost'}), [])

    def test_the_rate_limiter_stops_a_flood(self):
        limit = self.server.SOUND_PUSH_LIMIT
        allowed = [self.server._sound_rate_ok(1) for _ in range(limit + 3)]
        self.assertTrue(all(allowed[:limit]))
        self.assertFalse(any(allowed[limit:]),
                         "a sound flood was not rate limited")

    def test_the_rate_limit_is_per_user(self):
        for _ in range(self.server.SOUND_PUSH_LIMIT):
            self.server._sound_rate_ok(1)
        self.assertTrue(self.server._sound_rate_ok(2),
                        "one noisy recipient silenced everyone else")


class ActionButtonValidationTest(unittest.TestCase):
    """An 'action' button carries no form, so required fields must not block it."""

    def _source(self, relative):
        with open(os.path.join(REPO, relative), encoding='utf-8') as fh:
            return fh.read()

    def test_the_client_tells_the_server_which_kind_of_button_it_was(self):
        source = self._source('src/network/remote_ui.py')
        start = source.index('def _on_button')
        body = source[start:start + 3000]
        self.assertIn('kind=action', body.replace(' ', ''),
                      "the client no longer reports the button kind, so a "
                      "Refresh button would be validated as a submit")

    def test_the_server_skips_validation_for_non_submit_buttons(self):
        source = self._source('titan-net server/server.py')
        start = source.index('async def _build_screen')
        body = source[start:source.index('async def handle_open_remote_screen', start)]
        self.assertIn('strict=validate', body,
                      "the server no longer relaxes validation for "
                      "navigation, so a Refresh button would be blocked by "
                      "an empty required field")
        start = source.index('async def handle_remote_screen_action')
        body = source[start:start + 1500]
        self.assertIn("data.get('kind')", body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
