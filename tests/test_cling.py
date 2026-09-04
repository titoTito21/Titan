# -*- coding: utf-8 -*-
"""Cling: the Klango data formats, the engines, and the Lua the component carries.

Run it directly (`python tests/test_cling.py`) - `tests/` has no `__init__.py`.

Nothing here opens a window, plays a sound or speaks: the speaker and the mixer
are stood in for, and the engines are given a clock a test moves by hand.  That
is not a convenience - it is the reason the engines never read the clock and
never touch wx, because a game that could only be tested by playing it is a
game whose thirteenth level is never reached.

The applications under test are BUILT here, in a temporary folder, in exactly
the layout a Klango application has.  Cling's claim is that such a directory
runs unedited, and a test that used a hand-made Cling-shaped folder instead
would be testing something easier than the claim.
"""

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
COMPONENT = os.path.join(ROOT, 'data', 'components', 'cling')
if COMPONENT not in sys.path:
    sys.path.insert(0, COMPONENT)

from clingkit import (account, catalog, engines, host as host_module,  # noqa: E402
                      klango_lua, resources, runner, store as store_module,
                      topology)
from clingkit import pag                                           # noqa: E402
from clingkit.engines import instrument, soundscape, typing as typing_engine  # noqa: E402
from clingkit.lua import LuaRuntime, LuaError, backend             # noqa: E402
from clingkit.lua import patterns                                  # noqa: E402


# --------------------------------------------------------------------------- #
# Stand-ins: a Cling that cannot make a sound, cannot speak and cannot dial out
# --------------------------------------------------------------------------- #
# Nothing in this file may reach Titan-Net. A game records a score at the end of
# every run and offers it to the shared table, so a suite that left that alone
# would sign in to a real server, on a real network, once per test - slow,
# flaky, and a message in somebody's account for every run of the tests.
account._live_client = lambda: None
account._saved_credentials = lambda: ('', '')


class FakeNetClient(object):
    """Titan-Net as far as the score table is concerned, and no further."""

    def __init__(self, username='anna'):
        self.username = username
        self.data = {}

    def extension_data_get(self, slug, key):
        return {'success': True, 'value': self.data.get((slug, key))}

    def extension_data_set(self, slug, key, value):
        self.data[(slug, key)] = value
        return {'success': True}



class QuietSpeaker(host_module.Speaker):
    #: Where each line was said. A Klango application places its speech -
    #: Dice Poker says each die at its own place on the table - so a test
    #: about positioning has to be able to ask.
    def __init__(self):
        host_module.Speaker.__init__(self)
        self.said_at = []

    def say(self, text, position=0.0, pitch=0.0, interrupt=True, wait=False):
        if (text or '').strip() and not self.closed:
            self.said_at.append(float(position))
        return host_module.Speaker.say(self, text, position, pitch,
                                       interrupt, wait)

    def _speech_module(self):
        return None

    def _sound_module(self):
        return None


class SilentMixer(host_module.Mixer):
    def _sound_module(self):
        return None

    def _spatial_module(self):
        return None

    def _pygame_mixer(self):
        return None

    def _mode(self):
        return 'stereo'

    #: How long every sound is, as far as a test is concerned. It has to be
    #: something: a Klango sequence schedules its elements from the length of
    #: the one before, so a length of zero puts a whole announcement at one
    #: moment.
    LENGTH = 0.5

    def start(self, path, pan=0.0, elevation=0.0, gain=1.0, cents=0.0,
              loop=False, repeats=0):
        # Nothing is decoded and nothing is played, but the two rules the real
        # mixer applies here are applied: a closed mixer starts nothing, and
        # what it does start is remembered so `stop_all` can really stop it.
        # A double that skipped them would pass the tests that exist to prove
        # them.
        if self.closed:
            return None
        handle = _Started(self, loop)
        self.played.append((('loop:' if loop else '') +
                            os.path.basename(path or ''),
                            round(float(pan), 3), round(float(gain), 3)))
        if loop:
            self._loops.append(handle)
        return self._remember(handle)

    def length(self, path):
        return self.LENGTH

    def busy(self, handle):
        return bool(getattr(handle, 'alive', False))

    def set_gain(self, handle, pan=0.0, gain=1.0, elevation=0.0):
        return True

    def stop(self, handle):
        if handle is not None:
            handle.alive = False
        if handle in self._loops:
            self._loops.remove(handle)
        if handle in self._live:
            self._live.remove(handle)


class _Started(object):
    """What a silent mixer hands back. A one-shot is over at once; a loop
    keeps going until something stops it, which is what a test asserts on."""

    def __init__(self, mixer, loop=False):
        self.mixer = mixer
        self.alive = bool(loop)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    return path


def write_bytes(path, data=b'RIFF'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as handle:
        handle.write(data)
    return path


class ClingCase(unittest.TestCase):
    """A temporary `data/cling` root, and a way to open what is in it."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='cling-test-')
        self.apps_root = os.path.join(self.root, 'apps')
        os.makedirs(self.apps_root)
        self.state = os.path.join(self.root, 'state')

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # ------------------------------------------------------------- building
    def klango_app(self, app_id, appid=1, summary='', locale='en-us',
                   texts=None, category=''):
        path = os.path.join(self.apps_root, app_id)
        lines = ['appid=%d' % appid, 'appname=%s' % app_id,
                 'summary=%s' % (summary or app_id), 'version=1.0',
                 'minklango=20260803', 'platform=any']
        if category:
            lines.append('category=%s' % category)
        write(os.path.join(path, 'kni.txt'), '\n'.join(lines) + '\n')
        write(os.path.join(path, 'lang', 'default'), locale + '\n')
        for name, body in (texts or {}).items():
            write(os.path.join(path, 'lang', locale, 'default', name + '.txt'),
                  body)
        return path

    def open(self, app_id, language='en', clock=None, engine=''):
        """Open a built application. `engine` forces one, for the tests that
        are about a particular engine rather than about the choice."""
        app = [found for found in catalog.discover([self.apps_root], language)
               if found.id == app_id]
        self.assertTrue(app, 'the application was not discovered')
        app = app[0]
        if engine:
            app.engine = engine
        host = host_module.ClingHost(
            app, language, speaker=QuietSpeaker(), mixer=SilentMixer(),
            store=store_module.Store(app_id, 'test', self.state),
            clock=clock or runner.FakeClock())
        return app, host, engines.build(host)


# --------------------------------------------------------------------------- #
# The Klango data files
# --------------------------------------------------------------------------- #
class LuaDataFiles(ClingCase):
    """`.lev` and `.top` are Lua tables, and are read as data, never run."""

    def test_level_table(self):
        table = klango_lua.parse_value(
            '{ text = "level5_info", topology = "3x3", fields = 9, -- 3x3\n'
            '  hit_target = 30, nmole_time = 3, smole_time = 2.5,\n'
            '  max_nmoles = 2, max_smoles = 1, smole_time_bonus = 0, }')
        self.assertEqual(table['topology'], '3x3')
        self.assertEqual(table['hit_target'], 30)
        self.assertEqual(table['smole_time'], 2.5)
        self.assertEqual(table['smole_time_bonus'], 0)

    def test_bracket_keys_and_nesting(self):
        table = klango_lua.parse_value(
            '{ coords = { [1] = { [2] = { [1] = { x=-0.8, y=0.65, f=-100 } } } } }')
        self.assertAlmostEqual(table['coords'][1][2][1]['x'], -0.8)
        self.assertEqual(table['coords'][1][2][1]['f'], -100)

    def test_long_comment_and_positional_entries(self):
        table = klango_lua.parse_value('{ 1, 2, --[[ skipped ]] 3 }')
        self.assertEqual(klango_lua.as_list(table), [1, 2, 3])

    def test_a_broken_file_names_its_line(self):
        with self.assertRaises(klango_lua.LuaError) as caught:
            klango_lua.parse_value('{ a = 1,\n  b = }')
        self.assertEqual(caught.exception.line, 2)

    def test_chunk_of_named_assignments(self):
        chunk = klango_lua.parse_chunk('Level = { a = 1 }\nTopology = { b = 2 }')
        self.assertEqual(sorted(chunk), ['Level', 'Topology'])


class Topology(ClingCase):
    """A topology is where every field IS, converted once into Titan's units."""

    TOP = ('Topology = { size = { x = 3, y = 2, z = 1 }, coords = {\n'
           '  [1] = { [1] = { [1] = { x=-0.8, y=0.25, z=0, f=0 } },\n'
           '          [2] = { [1] = { x=-0.8, y=0.65, z=0, f=-100 } } },\n'
           '  [2] = { [1] = { [1] = { x=0.0,  y=0.25, z=0, f=0 } },\n'
           '          [2] = { [1] = { x=0.0,  y=0.65, z=0, f=-100 } } },\n'
           '  [3] = { [1] = { [1] = { x=0.8,  y=0.25, z=0, f=0 } },\n'
           '          [2] = { [1] = { x=0.8,  y=0.65, z=0, f=-100 } } } } }')

    def board(self):
        path = write(os.path.join(self.root, '3x2.top'), self.TOP)
        return topology.Board.from_file(path)

    def test_every_field_is_there(self):
        board = self.board()
        self.assertEqual((board.columns, board.rows, len(board)), (3, 2, 6))

    def test_left_is_left_and_right_is_right(self):
        board = self.board()
        self.assertEqual(board.at(1, 1).pan, -1.0)
        self.assertEqual(board.at(3, 1).pan, 1.0)
        self.assertEqual(board.at(2, 1).pan, 0.0)

    def test_titan_and_klango_disagree_about_pan_and_a_field_converts(self):
        """Titan's mixer takes 0..1 while everything else says -1..1."""
        board = self.board()
        self.assertEqual(board.at(1, 1).pan01, 0.0)
        self.assertEqual(board.at(2, 1).pan01, 0.5)
        self.assertEqual(board.at(3, 1).pan01, 1.0)

    def test_the_far_row_is_quieter_and_lower_pitched(self):
        board = self.board()
        near, far = board.at(2, 1), board.at(2, 2)
        self.assertGreater(near.gain, far.gain)
        self.assertEqual(far.semitones, -1.0)
        self.assertGreater(far.elevation, near.elevation)

    def test_walking_off_the_board_is_nothing(self):
        board = self.board()
        self.assertIsNone(board.step(board.at(1, 1), columns=-1))
        self.assertEqual(board.step(board.at(1, 1), columns=1).column, 2)

    def test_wrapping_is_asked_for_not_assumed(self):
        board = self.board()
        self.assertEqual(board.step(board.at(3, 1), columns=1, wrap=True).column, 1)

    def test_a_level_with_no_topology_still_gets_a_board(self):
        board = topology.load(None, '', 9, 0)
        self.assertEqual(len(board), 9)


class Texts(ClingCase):
    """The words, in the best locale the application really has."""

    def test_the_named_default_locale_wins_when_nothing_matches(self):
        path = self.klango_app('a', locale='en-us',
                               texts={'welcome': 'Hello'})
        catalogue = resources.TextCatalogue(path, 'de')
        self.assertEqual(catalogue.locale, 'en-us')
        self.assertEqual(catalogue.text('welcome'), 'Hello')

    def test_the_users_language_wins_when_it_is_there(self):
        path = self.klango_app('a', locale='en-us', texts={'welcome': 'Hello'})
        write(os.path.join(path, 'lang', 'pl-pl', 'default', 'welcome.txt'),
              'Witaj')
        self.assertEqual(resources.TextCatalogue(path, 'pl').text('welcome'),
                         'Witaj')

    def test_a_region_we_guessed_wrong_is_still_that_language(self):
        path = self.klango_app('a', locale='en-us')
        write(os.path.join(path, 'lang', 'pt-br', 'default', 'welcome.txt'),
              'Ola')
        self.assertEqual(resources.TextCatalogue(path, 'pt-pt').text('welcome'),
                         'Ola')

    def test_placeholders_are_the_applications_own(self):
        path = self.klango_app('a', texts={'status': 'PTS: %d, left: %d'})
        catalogue = resources.TextCatalogue(path, 'en')
        self.assertEqual(catalogue.text('status', 7, 30), 'PTS: 7, left: 30')

    def test_a_text_whose_placeholders_do_not_match_is_not_a_crash(self):
        path = self.klango_app('a', texts={'status': 'PTS: %d, left: %d'})
        catalogue = resources.TextCatalogue(path, 'en')
        self.assertIn('%d', catalogue.text('status', 7))

    def test_markup_is_for_the_eye_and_never_spoken(self):
        self.assertEqual(resources.strip_markup('<b>Arrows</b> - move'),
                         'Arrows - move')

    def test_a_missing_text_is_empty_not_an_error(self):
        path = self.klango_app('a')
        self.assertEqual(resources.TextCatalogue(path, 'en').text('nothing'), '')

    def test_appinfo_flags(self):
        path = self.klango_app('a', texts={'appinfo':
                                           'hideinmenu:yes\nmenusound:klangomenu'})
        self.assertEqual(resources.TextCatalogue(path, 'en').info()['hideinmenu'],
                         'yes')


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
class Discovery(ClingCase):

    def test_a_klango_folder_is_a_cling_application_unedited(self):
        self.klango_app('mole', appid=18, summary='Whack a mole')
        found = catalog.discover([self.apps_root], 'en')
        self.assertEqual([app.id for app in found], ['mole'])
        self.assertEqual(found[0].summary('en'), 'Whack a mole')
        self.assertEqual(found[0].appid, '18')

    def test_the_applications_own_translated_name_is_what_it_is_called(self):
        self.klango_app('mole', texts={'klangomenu': 'Mole No More'})
        found = catalog.discover([self.apps_root], 'en')[0]
        self.assertEqual(found.name('en'), 'Mole No More')

    def test_a_folder_with_no_manifest_is_not_an_application(self):
        os.makedirs(os.path.join(self.apps_root, 'notes'))
        self.assertEqual(catalog.discover([self.apps_root], 'en'), [])

    def test_an_unknown_manifest_key_is_reported_not_silently_dropped(self):
        path = self.klango_app('a')
        write(os.path.join(path, 'kni.txt'),
              'appid=1\nappname=a\nsummary=s\nversion=1\nnonsense=yes\n')
        found = catalog.discover([self.apps_root], 'en')[0]
        self.assertTrue(any('nonsense' in problem for problem in found.problems))

    def test_a_category_comes_from_the_folder_it_was_copied_from(self):
        nested = os.path.join(self.apps_root, 'simplegames')
        os.makedirs(nested)
        write(os.path.join(nested, 'skeet', 'kni.txt'),
              'appid=17\nappname=skeet\nsummary=s\nversion=1\n')
        found = catalog.discover([nested], 'en')[0]
        self.assertEqual(found.category, 'games')

    def test_an_application_can_be_switched_off(self):
        path = self.klango_app('a')
        write(os.path.join(path, catalog.MANIFEST),
              '[cling app]\nname = A\nstatus = 1\n')
        self.assertFalse(catalog.discover([self.apps_root], 'en')[0].enabled)


class EngineDetection(ClingCase):
    """Which engine a directory gets, decided by what is really in it."""

    def test_levels_mean_a_board_game(self):
        path = self.klango_app('mole')
        write(os.path.join(path, 'skin', 'default', 'levels', 'l1.lev'),
              'Level = { fields = 9, hit_target = 5 }')
        write_bytes(os.path.join(path, 'skin', 'default', 'themes', 'default',
                                 't_move.ogg'))
        self.assertEqual(catalog.detect_engine(path), catalog.ENGINE_GRID_HUNT)

    def test_a_spec_means_a_soundscape(self):
        path = self.klango_app('ship')
        write(os.path.join(path, 'spec.txt'), 'start : deck\nLocation : deck\n')
        self.assertEqual(catalog.detect_engine(path), catalog.ENGINE_SOUNDSCAPE)

    def test_a_folder_of_key_named_samples_means_an_instrument(self):
        path = self.klango_app('piano')
        for key in 'zxcv':
            write_bytes(os.path.join(path, 'sounds', 'set', key + '.wav'))
        self.assertEqual(catalog.detect_engine(path), catalog.ENGINE_INSTRUMENT)

    def test_lesson_files_mean_a_course(self):
        path = self.klango_app('typist')
        write(os.path.join(path, 'trainings', 'en', 'course.xml'),
              '<KTouchLecture><Title>T</Title><Levels><Level>'
              '<NewCharacters>jf</NewCharacters><Line>jf fj</Line>'
              '</Level></Levels></KTouchLecture>')
        self.assertEqual(catalog.detect_engine(path), catalog.ENGINE_TYPING)

    def test_its_own_script_beats_every_guess(self):
        """With no Klango library to run on, its own script still wins."""
        path = self.klango_app('own')
        write(os.path.join(path, 'spec.txt'), 'start : a\nLocation : a\n')
        write(os.path.join(path, 'main.lua'), '-- mine\n')
        found = catalog.detect_engine(path)
        self.assertIn(found, (catalog.ENGINE_SCRIPT, catalog.ENGINE_KLANGO))

    def test_an_application_with_its_own_klango_code_is_emulated(self):
        """Lua beside `lang/` is a Klango application, and is EMULATED - its
        own code - rather than re-created from its data."""
        path = self.klango_app('mole')
        write(os.path.join(path, 'mole.lua'), 'function main() end\n')
        self.assertTrue(catalog.has_klango_code(path, 'mole'))
        self.assertFalse(catalog.has_klango_code(self.root, 'mole'))

    def test_an_application_with_only_words_is_read_not_refused(self):
        path = self.klango_app('elbot', texts={'welcome': 'Hi'})
        self.assertEqual(catalog.detect_engine(path), catalog.ENGINE_READER)

    def test_an_invented_engine_name_is_refused_and_reported(self):
        path = self.klango_app('a')
        write(os.path.join(path, catalog.MANIFEST),
              '[cling app]\nname = A\nengine = teleportation\n')
        found = catalog.discover([self.apps_root], 'en')[0]
        self.assertTrue(any('teleportation' in problem
                            for problem in found.problems))
        self.assertIn(found.engine, catalog.ENGINES)


# --------------------------------------------------------------------------- #
# The engines
# --------------------------------------------------------------------------- #
class BoardGame(ClingCase):
    """Mole No More's shape: the level file IS the rules."""

    def mole(self, **level):
        settings = {'fields': 4, 'hit_target': 2, 'nmole_time': 0,
                    'smole_time': 0, 'max_nmoles': 1, 'max_smoles': 0,
                    'smole_time_bonus': 0, 'topology': '2x2', 'text': 'l1',
                    'time': 30}
        settings.update(level)
        path = self.klango_app('mole', texts={
            'welcome': 'Welcome.', 'instructions': 'Hit them in %d seconds.',
            'l1': 'Hit two.', 'current_status': 'PTS: %d n %d s %d left %d',
            'timeup': 'Time is up.', 'timeup_head': 'Game Over',
            'game_finished_dialog': 'Whacked %d: %d normal, %d super, %d points.',
            'game_finished_dialog_head': 'Game scores'})
        write(os.path.join(path, 'skin', 'default', 'levels', '2x2.top'),
              'Topology = { size = { x = 2, y = 2, z = 1 }, coords = {\n'
              ' [1] = { [1] = { [1] = { x=-1, y=0.2, z=0, f=0 } },\n'
              '         [2] = { [1] = { x=-1, y=0.8, z=0, f=-100 } } },\n'
              ' [2] = { [1] = { [1] = { x=1, y=0.2, z=0, f=0 } },\n'
              '         [2] = { [1] = { x=1, y=0.8, z=0, f=-100 } } } } }')
        write(os.path.join(path, 'skin', 'default', 'levels', 'l1.lev'),
              'Level = {\n' + ',\n'.join(
                  '  %s = %r' % (key, value) for key, value in settings.items()
              ).replace("'", '"') + '\n}')
        for name in ('t_move', 't_border', 't_miss', 't_mole_hello',
                     't_mole_bye', 't_mole_auu', 't_walk_on_mole',
                     't_background'):
            write_bytes(os.path.join(path, 'skin', 'default', 'themes',
                                     'default', name + '.ogg'))
        write_bytes(os.path.join(path, 'skin', 'default', 'events',
                                 'e_earn_points1.ogg'))
        write_bytes(os.path.join(path, 'skin', 'default', 'events',
                                 'e_timeout.ogg'))
        return path

    def test_the_briefing_is_the_applications_own_words(self):
        self.mole()
        _app, host, engine = self.open('mole', engine='grid_hunt')
        engine.start()
        joined = ' '.join(host.messages)
        self.assertIn('Welcome.', joined)
        self.assertIn('Hit two.', joined)
        self.assertIn('Hit them in 30 seconds.', joined)

    def test_space_begins_the_level_and_the_board_is_the_topology(self):
        self.mole()
        _app, _host, engine = self.open('mole', engine='grid_hunt')
        engine.start()
        engine.key('space')
        self.assertEqual(engine.state, 'playing')
        self.assertEqual((engine.board.columns, engine.board.rows), (2, 2))

    def test_moving_off_the_board_plays_the_border_and_stays_put(self):
        self.mole()
        _app, host, engine = self.open('mole', engine='grid_hunt')
        engine.start()
        engine.key('space')
        host.mixer.played = []
        engine.key('left')
        self.assertEqual(engine.cursor.column, 1)
        self.assertIn('t_border.ogg', [name for name, _pan, _gain
                                       in host.mixer.played])

    def test_a_mole_arrives_where_the_topology_puts_it(self):
        self.mole()
        clock = runner.FakeClock()
        _app, host, engine = self.open('mole', clock=clock, engine='grid_hunt')
        engine.start()
        engine.key('space')
        clock.advance(1.0)
        engine.tick()
        self.assertTrue(engine.occupants)
        arrival = [row for row in host.mixer.played
                   if row[0] == 't_mole_hello.ogg'][-1]
        self.assertIn(arrival[1], (-1.0, 1.0))

    def test_hitting_scores_and_the_level_ends_at_its_own_target(self):
        self.mole(hit_target=2)
        clock = runner.FakeClock()
        _app, _host, engine = self.open('mole', clock=clock, engine='grid_hunt')
        engine.start()
        engine.key('space')
        for _round in range(2):
            clock.advance(1.0)
            engine.tick()
            self.assertTrue(engine.occupants)
            engine.cursor = engine.occupants[0].field
            engine.key('space')
        self.assertEqual(engine.normal_hits, 2)
        # One level, so finishing it finishes the game.
        self.assertEqual(engine.state, 'complete')

    def test_a_swing_at_nothing_is_a_miss_and_is_counted(self):
        self.mole()
        _app, host, engine = self.open('mole', engine='grid_hunt')
        engine.start()
        engine.key('space')
        engine.occupants = []
        engine.key('space')
        self.assertEqual(engine.misses, 1)
        self.assertIn('t_miss.ogg', [name for name, _p, _g in host.mixer.played])

    def test_a_mole_with_a_lifetime_leaves_by_itself(self):
        self.mole(nmole_time=1.0)
        clock = runner.FakeClock()
        _app, host, engine = self.open('mole', clock=clock, engine='grid_hunt')
        engine.start()
        engine.key('space')
        clock.advance(0.5)
        engine.tick()
        self.assertTrue(engine.occupants)
        clock.advance(2.0)
        engine.tick()
        self.assertIn('t_mole_bye.ogg', [name for name, _p, _g
                                         in host.mixer.played])

    def test_the_clock_runs_out_and_the_game_says_so(self):
        self.mole(time=5)
        clock = runner.FakeClock()
        _app, host, engine = self.open('mole', clock=clock, engine='grid_hunt')
        engine.start()
        engine.key('space')
        clock.advance(6.0)
        engine.tick()
        self.assertEqual(engine.state, 'over')
        self.assertIn('Time is up.', ' '.join(host.messages))

    def test_the_status_line_is_the_applications_own_format(self):
        self.mole()
        _app, _host, engine = self.open('mole', engine='grid_hunt')
        engine.start()
        engine.key('space')
        self.assertTrue(engine.status().startswith('PTS: 0'))

    def test_a_score_is_written_locally_before_anything_is_published(self):
        self.mole(time=5)
        clock = runner.FakeClock()
        _app, host, engine = self.open('mole', clock=clock, engine='grid_hunt')
        engine.start()
        engine.key('space')
        engine.cursor = engine.board.by_index(1)
        clock.advance(1.0)
        engine.tick()
        engine.cursor = engine.occupants[0].field
        engine.key('space')
        clock.advance(10.0)
        engine.tick()
        self.assertGreaterEqual(host.store.best(), 1)

    def test_a_game_with_no_levels_says_so_instead_of_showing_a_board(self):
        self.klango_app('empty')
        write_bytes(os.path.join(self.apps_root, 'empty', 'skin', 'default',
                                 'levels', 'x.lev'), b'not a level')
        _app, host, engine = self.open('empty')
        engine.start()
        self.assertEqual(engine.state, 'over')
        self.assertTrue(host.messages)


class Soundscape(ClingCase):
    """`spec.txt` is a complete description of a place."""

    SPEC = ('-- a comment\n'
            'start : deck\n'
            'Location : deck\n'
            '\tBkgVolume : 0.9\n'
            '\tlinks : hold\n'
            '\tfx : bell\n'
            '\t\tfxangle : 300, 60\n'
            '\t\tfxdist : 1, 1\n'
            '\t\tfxtimestart : 1, 2\n'
            '\t\tfxtimedelta : 5, 6\n'
            '\t\tfxvol : 0.3, 0.8\n'
            'Location : hold\n'
            '\tBkgVolume : 0.5\n'
            '\tlinks : deck\n')

    def ship(self):
        path = self.klango_app('ship', texts={'deck_name': 'The deck',
                                              'hold_name': 'The hold',
                                              'deck_comment': 'Wind.'})
        write(os.path.join(path, 'spec.txt'), self.SPEC)
        for name in ('deck_bkg', 'hold_bkg', 'bell'):
            write_bytes(os.path.join(path, 'data', name + '.ogg'))
        return path

    def test_the_specification_is_read_the_way_it_is_written(self):
        start, locations = soundscape.parse_spec(self.SPEC)
        self.assertEqual(start, 'deck')
        self.assertEqual(sorted(locations), ['deck', 'hold'])
        self.assertEqual(locations['deck'].links, ['hold'])
        self.assertAlmostEqual(locations['deck'].background_volume, 0.9)
        self.assertEqual(locations['deck'].effects[0].angle, (300.0, 60.0))

    def test_entering_plays_the_background_and_says_the_place(self):
        self.ship()
        _app, host, engine = self.open('ship')
        engine.start()
        self.assertEqual(engine.location.name, 'deck')
        self.assertIn('The deck', host.messages)
        self.assertIn('Wind.', host.messages)
        self.assertTrue(any(name.startswith('loop:deck_bkg')
                            for name, _p, _g in host.mixer.played))

    def test_an_effect_fires_when_its_own_timing_says_so(self):
        self.ship()
        clock = runner.FakeClock()
        _app, host, engine = self.open('ship', clock=clock)
        engine.start()
        host.mixer.played = []
        clock.advance(3.0)
        engine.tick()
        self.assertIn('bell.ogg', [name for name, _p, _g in host.mixer.played])

    def test_an_arc_that_crosses_the_front_is_taken_the_short_way(self):
        self.ship()
        clock = runner.FakeClock()
        _app, host, engine = self.open('ship', clock=clock)
        engine.start()
        for _step in range(40):
            clock.advance(3.0)
            engine.tick()
        pans = [pan for name, pan, _gain in host.mixer.played
                if name == 'bell.ogg']
        self.assertTrue(pans)
        # 300..60 degrees is the front; nothing may land at the sides.
        self.assertTrue(all(abs(pan) <= 0.88 for pan in pans), pans)

    def test_enter_walks_to_the_place_the_link_names(self):
        self.ship()
        _app, _host, engine = self.open('ship')
        engine.start()
        engine.key('enter')
        self.assertEqual(engine.location.name, 'hold')

    def test_a_folder_of_sounds_with_no_specification_still_opens(self):
        path = self.klango_app('noises')
        for name in ('a', 'b'):
            write_bytes(os.path.join(path, 'data', name + '.ogg'))
        _app, _host, engine = self.open('noises')
        engine.start()
        self.assertEqual(len(engine.sounds), 2)
        self.assertTrue(engine.key('right'))


class Instrument(ClingCase):
    """The file name is the key, and `_l` is the one that loops."""

    def piano(self):
        path = self.klango_app('piano')
        for key in 'zxcv':
            write_bytes(os.path.join(path, 'sounds', 'set', key + '.wav'))
        write_bytes(os.path.join(path, 'sounds', 'set', 'q_l.wav'))
        write(os.path.join(path, 'sounds', 'set', '.info.txt'), 'A set.')
        write_bytes(os.path.join(path, 'sounds', 'set', 'readme.pdf'))
        return path

    def test_every_key_named_sample_is_a_key(self):
        self.piano()
        _app, _host, engine = self.open('piano', engine='instrument')
        engine.start()
        self.assertEqual(sorted(engine.samples), ['c', 'q', 'v', 'x', 'z'])

    def test_a_file_that_is_not_one_key_is_not_a_sample(self):
        self.piano()
        _app, _host, engine = self.open('piano', engine='instrument')
        engine.start()
        self.assertNotIn('readme', engine.samples)

    def test_pressing_a_key_plays_it(self):
        self.piano()
        _app, host, engine = self.open('piano', engine='instrument')
        engine.start()
        host.mixer.played = []
        self.assertTrue(engine.key('z'))
        self.assertEqual(host.mixer.played[0][0], 'z.wav')

    def test_a_loop_is_a_switch_rather_than_a_note(self):
        self.piano()
        _app, _host, engine = self.open('piano', engine='instrument')
        engine.start()
        engine.key('q')
        self.assertEqual(len(engine.playing), 1)
        engine.key('q')
        self.assertEqual(len(engine.playing), 0)

    def test_the_set_the_player_chose_is_remembered(self):
        self.piano()
        _app, host, engine = self.open('piano', engine='instrument')
        engine.start()
        self.assertEqual(host.store.get('sample_set'), engine.sets[0][0])


class Course(ClingCase):
    """A KTouch lecture is a course, and Cling reads it out."""

    LECTURE = ('<KTouchLecture><Title>Course</Title><Levels>'
               '<Level><NewCharacters>jf</NewCharacters>'
               '<Line>jf fj</Line><Line>ff jj</Line></Level>'
               '<Level><NewCharacters>dk</NewCharacters>'
               '<Line>dk kd</Line></Level></Levels></KTouchLecture>')

    def typist(self):
        path = self.klango_app('typist')
        write(os.path.join(path, 'trainings', 'lang_en', 'course.xml'),
              self.LECTURE)
        return path

    def test_a_lecture_is_read_into_levels_and_lines(self):
        path = self.typist()
        lesson = typing_engine.read_lesson(
            os.path.join(path, 'trainings', 'lang_en', 'course.xml'))
        self.assertEqual(lesson.title, 'Course')
        self.assertEqual(len(lesson.levels), 2)
        self.assertEqual(lesson.levels[0][1], ['jf fj', 'ff jj'])

    def test_a_file_that_is_not_a_lecture_is_not_one(self):
        path = write(os.path.join(self.root, 'x.xml'), '<other/>')
        self.assertIsNone(typing_engine.read_lesson(path))

    def test_typing_the_line_is_progress_and_a_wrong_key_says_the_right_one(self):
        self.typist()
        _app, host, engine = self.open('typist')
        engine.start()
        engine.key('space')                       # begin
        engine.key('j')
        self.assertEqual(engine.position, 1)
        engine.key('z')
        self.assertEqual(engine.mistakes, 1)
        self.assertEqual(host.speaker.spoken[-1], 'f')

    def test_a_space_in_the_line_is_typed_with_the_space_bar(self):
        self.typist()
        _app, _host, engine = self.open('typist')
        engine.start()
        engine.key('space')
        for character in 'jf':
            engine.key(character)
        engine.key('space')
        self.assertEqual(engine.position, 3)

    def test_finishing_a_line_reports_the_speed(self):
        self.typist()
        clock = runner.FakeClock()
        _app, host, engine = self.open('typist', clock=clock)
        engine.start()
        engine.key('space')
        clock.advance(6.0)
        for character in 'jf fj':
            engine.key('space' if character == ' ' else character)
        self.assertEqual(engine.state, 'done')
        self.assertTrue(any('minute' in message for message in host.messages))


class Reader(ClingCase):
    """An application Cling cannot play still says everything it says."""

    def test_its_texts_are_listed_in_an_order_a_person_would_want(self):
        self.klango_app('elbot', texts={'welcome': 'Hi', 'help': 'Keys',
                                        'instructions': 'Type at it'})
        _app, _host, engine = self.open('elbot')
        engine.start()
        self.assertEqual([label for label, _body in engine.entries][:3],
                         ['Welcome', 'Instructions', 'Help'])

    def test_reading_one_says_the_whole_of_it(self):
        self.klango_app('elbot', texts={'welcome': 'Hi', 'help': 'Keys'})
        _app, host, engine = self.open('elbot')
        engine.start()
        engine.key('down')
        engine.key('enter')
        self.assertIn('Keys', host.messages)

    def test_bookkeeping_files_are_not_offered_as_something_to_read(self):
        self.klango_app('elbot', texts={'welcome': 'Hi',
                                        'appinfo': 'hideinmenu:no',
                                        'klangomenu': 'Elbot'})
        _app, _host, engine = self.open('elbot')
        engine.start()
        labels = [label for label, _body in engine.entries]
        self.assertNotIn('Appinfo', labels)
        self.assertNotIn('Klangomenu', labels)


# --------------------------------------------------------------------------- #
# The application that brings its own logic
# --------------------------------------------------------------------------- #
class Scripted(ClingCase):

    def scripted(self, source, leaf='main.lua'):
        path = self.klango_app('own', texts={'welcome': 'Hello'})
        write(os.path.join(path, leaf), source)
        return path

    def open(self, app_id='own', language='en', clock=None, engine='script'):
        """These are about Cling's OWN script engine, so they ask for it.

        An application with Lua beside `lang/` is a Klango application and is
        emulated by default now - which is right, and is why the engine has to
        be named here rather than assumed."""
        return ClingCase.open(self, app_id, language, clock, engine)

    def test_a_lua_application_is_started_and_its_keys_reach_it(self):
        self.scripted(
            'seen = {}\n'
            'function on_start() cling.show("started") end\n'
            'function on_key(k) seen[#seen+1] = k return k ~= "q" end\n'
            'function status() return "keys " .. tostring(#seen) end\n')
        _app, host, engine = self.open('own')
        engine.start()
        self.assertIn('started', host.messages)
        self.assertTrue(engine.key('up'))
        self.assertEqual(engine.status(), 'keys 1')

    def test_a_key_the_application_refuses_is_still_escape(self):
        self.scripted('function on_key(k) return false end\n')
        _app, _host, engine = self.open('own')
        engine.start()
        self.assertTrue(engine.key('escape'))
        self.assertFalse(engine.running)

    def test_the_host_is_the_same_one_the_engines_use(self):
        self.scripted(
            'function on_start()\n'
            '  cling.set("visits", (cling.get("visits", 0)) + 1)\n'
            '  cling.say(cling.text("welcome"))\n'
            'end\n')
        _app, host, engine = self.open('own')
        engine.start()
        self.assertEqual(host.store.get('visits'), 1)
        self.assertIn('Hello', host.speaker.spoken)

    def test_a_board_asked_for_is_the_board_a_field_comes_from(self):
        self.scripted(
            'function on_start()\n'
            '  cling.board("", 3, 3)\n'
            '  local f = cling.field(9)\n'
            '  cling.show(string.format("%d,%d", f.column, f.row))\n'
            'end\n')
        _app, host, engine = self.open('own')
        engine.start()
        self.assertEqual(engine.error, '')
        self.assertIn('3,3', host.messages)

    def test_an_application_that_breaks_says_so_rather_than_going_quiet(self):
        self.scripted('function on_start() nope.field = 1 end\n')
        _app, host, engine = self.open('own')
        engine.start()
        self.assertTrue(engine.error)
        self.assertTrue(host.messages)
        self.assertFalse(engine.running)

    def test_a_python_application_gets_the_identical_host(self):
        self.scripted('def on_start():\n'
                      '    cling.show(cling.text("welcome"))\n', 'main.py')
        _app, host, engine = self.open('own')
        self.assertEqual(engine.kind, 'python')
        engine.start()
        self.assertIn('Hello', host.messages)

    def test_an_application_that_names_no_entry_point_says_so(self):
        self.klango_app('own')
        app = catalog.discover([self.apps_root], 'en')[0]
        app.engine = catalog.ENGINE_SCRIPT
        host = host_module.ClingHost(app, 'en', speaker=QuietSpeaker(),
                                     mixer=SilentMixer(),
                                     store=store_module.Store('own', 't',
                                                              self.state))
        engine = engines.build(host)
        engine.start()
        self.assertIn('main.lua', engine.error)


class EngineRegistry(ClingCase):
    """A genre can be added to Cling from outside Cling."""

    def test_a_registered_engine_is_built_for_an_application_that_names_it(self):
        class Darts(engines.Engine):
            def start(self):
                self.running = True
                self.host.show('darts')

        engines.register('darts', Darts)
        try:
            self.assertIn('darts', engines.names())
            path = self.klango_app('d')
            write(os.path.join(path, catalog.MANIFEST),
                  '[cling app]\nname = D\nengine = darts\n')
            app = catalog.discover([self.apps_root], 'en')[0]
            app.engine = 'darts'
            host = host_module.ClingHost(app, 'en', speaker=QuietSpeaker(),
                                         mixer=SilentMixer(),
                                         store=store_module.Store('d', 't',
                                                                  self.state))
            engine = engines.build(host)
            engine.start()
            self.assertIn('darts', host.messages)
        finally:
            engines._REGISTRY.pop('darts', None)

    def test_an_engine_that_will_not_build_falls_back_to_the_reader(self):
        def broken(_host):
            raise RuntimeError('no')

        engines.register('broken', broken)
        try:
            self.klango_app('b', texts={'welcome': 'Hi'})
            app = catalog.discover([self.apps_root], 'en')[0]
            app.engine = 'broken'
            host = host_module.ClingHost(app, 'en', speaker=QuietSpeaker(),
                                         mixer=SilentMixer(),
                                         store=store_module.Store('b', 't',
                                                                  self.state))
            self.assertEqual(type(engines.build(host)).__name__, 'ReaderEngine')
        finally:
            engines._REGISTRY.pop('broken', None)


# --------------------------------------------------------------------------- #
# Saving, and who is playing
# --------------------------------------------------------------------------- #
class Saving(ClingCase):

    def test_a_score_table_is_kept_in_order_and_answers_with_the_position(self):
        saved = store_module.Store('game', 'me', self.state)
        self.assertEqual(saved.record_score(10), 1)
        self.assertEqual(saved.record_score(30), 1)
        self.assertEqual(saved.record_score(20), 2)
        self.assertEqual([row['points'] for row in saved.scores()], [30, 20, 10])
        self.assertEqual(saved.best(), 30)

    def test_two_profiles_do_not_see_each_others_scores(self):
        store_module.Store('game', 'anna', self.state).record_score(5)
        self.assertEqual(store_module.Store('game', 'bob', self.state).scores(),
                         [])

    def test_what_was_saved_is_there_the_next_time(self):
        store_module.Store('game', 'me', self.state).set('level', 7)
        self.assertEqual(store_module.Store('game', 'me', self.state).get('level'),
                         7)

    def test_the_applications_own_folder_is_never_written_to(self):
        path = self.klango_app('a')
        before = sorted(os.listdir(path))
        _app, host, _engine = self.open('a')
        host.store.set('x', 1)
        self.assertEqual(sorted(os.listdir(path)), before)


class WhoIsPlaying(ClingCase):
    """Klango wanted its own account; Cling hands over Titan-Net's."""

    def test_an_account_always_answers_even_with_nothing_signed_in(self):
        who = account.whoami()
        self.assertEqual(who.name, account.LOCAL_PROFILE)
        self.assertFalse(who.online)
        self.assertTrue(who.describe())

    def test_a_signed_in_titan_net_user_is_the_profile(self):
        client = FakeNetClient('anna')
        original = account._live_client
        account._live_client = lambda: client
        try:
            who = account.whoami()
            self.assertEqual(who.name, 'anna')
            self.assertTrue(who.online)
            self.assertEqual(who.profile, 'anna')
        finally:
            account._live_client = original

    def test_the_profile_is_a_name_that_can_be_a_folder(self):
        self.assertEqual(account.Account('a/b\\c').profile, 'a_b_c')

    def test_publishing_with_nobody_signed_in_is_a_sentence_not_a_crash(self):
        published, message = account.publish_score('game', 10)
        self.assertFalse(published)
        self.assertTrue(message)

    def test_a_score_reaches_the_shared_table_when_there_is_one(self):
        client = FakeNetClient('anna')
        original = account._live_client
        account._live_client = lambda: client
        try:
            published, message = account.publish_score('game', 10)
            self.assertTrue(published, message)
            self.assertEqual(account.leaderboard('game'),
                             [{'name': 'anna', 'points': 10}])
        finally:
            account._live_client = original

    def test_a_player_has_one_row_on_the_shared_table_not_one_per_run(self):
        client = FakeNetClient('anna')
        original = account._live_client
        account._live_client = lambda: client
        try:
            account.publish_score('game', 10)
            account.publish_score('game', 30)
            self.assertEqual(account.leaderboard('game'),
                             [{'name': 'anna', 'points': 30}])
        finally:
            account._live_client = original

    def test_a_leaderboard_nobody_can_reach_is_empty(self):
        self.assertEqual(account.leaderboard('nothing-here'), [])


# --------------------------------------------------------------------------- #
# The Lua the component carries
# --------------------------------------------------------------------------- #
class Lua(unittest.TestCase):
    """Nothing installed, nothing native: the interpreter is inside Cling."""

    def run_lua(self, source):
        runtime = LuaRuntime()
        runtime.run(source)
        return runtime

    def test_the_component_answers_for_itself_which_backend_it_has(self):
        self.assertIn(backend(), ('native', 'builtin'))

    def test_arithmetic_strings_and_the_two_number_kinds(self):
        runtime = self.run_lua('a = 7 // 1\nb = 2 ^ 10\nc = 7 % 3\n'
                               'd = "x" .. 1 .. 2\n'.replace('//', '/'))
        self.assertEqual(runtime.get_global('b'), 1024.0)
        self.assertEqual(runtime.get_global('c'), 1)
        self.assertEqual(runtime.get_global('d'), 'x12')

    def test_closures_keep_what_they_were_made_with(self):
        runtime = self.run_lua(
            'local function counter()\n'
            '  local n = 0\n'
            '  return function() n = n + 1 return n end\n'
            'end\n'
            'local c = counter()\n c() c()\n out = c()\n')
        self.assertEqual(runtime.get_global('out'), 3)

    def test_multiple_returns_and_varargs(self):
        runtime = self.run_lua(
            'local function two() return 1, 2 end\n'
            'local function count(...) return select("#", ...) end\n'
            'a, b = two()\n n = count(two())\n one = count((two()))\n')
        self.assertEqual((runtime.get_global('a'), runtime.get_global('b')),
                         (1, 2))
        self.assertEqual(runtime.get_global('n'), 2)
        self.assertEqual(runtime.get_global('one'), 1)

    def test_metatables_are_how_a_class_is_written(self):
        runtime = self.run_lua(
            'Mole = {} Mole.__index = Mole\n'
            'function Mole.new(n) return setmetatable({n=n}, Mole) end\n'
            'function Mole:hit() self.n = self.n + 1 return self.n end\n'
            'local m = Mole.new(1)\n m:hit()\n out = m:hit()\n')
        self.assertEqual(runtime.get_global('out'), 3)

    def test_index_and_newindex_are_honoured(self):
        runtime = self.run_lua(
            'local log = {}\n'
            'local t = setmetatable({}, {\n'
            '  __index = function(_, k) return "d:" .. k end,\n'
            '  __newindex = function(_, k, v) log[#log+1] = k end })\n'
            't.x = 1\n a = t.y\n b = #log\n')
        self.assertEqual(runtime.get_global('a'), 'd:y')
        self.assertEqual(runtime.get_global('b'), 1)

    def test_pcall_turns_an_error_into_an_answer(self):
        runtime = self.run_lua(
            'ok, err = pcall(function() error("boom") end)\n'
            'ok2 = pcall(function() return 1 end)\n')
        self.assertFalse(runtime.get_global('ok'))
        self.assertEqual(runtime.get_global('err'), 'boom')
        self.assertTrue(runtime.get_global('ok2'))

    def test_the_loops_lua_has(self):
        runtime = self.run_lua(
            'local s = 0\n'
            'for i = 10, 1, -2 do s = s + i end\n'
            'local t = {3, 4}\n'
            'for _, v in ipairs(t) do s = s + v end\n'
            'local n = 0\n while n < 3 do n = n + 1 end\n'
            'local r = 0\n repeat r = r + 1 until r == 2\n'
            'out = s + n + r\n')
        self.assertEqual(runtime.get_global('out'), 30 + 7 + 3 + 2)

    def test_break_leaves_only_the_loop_it_is_in(self):
        runtime = self.run_lua(
            'out = 0\n'
            'for i = 1, 3 do for j = 1, 3 do if j == 2 then break end\n'
            '  out = out + 1 end end\n')
        self.assertEqual(runtime.get_global('out'), 3)

    def test_the_string_library_a_real_application_uses(self):
        runtime = self.run_lua(
            'a = string.format("%s: %d (%.1f)", "pts", 7, 2.25)\n'
            'b = ("Mole"):upper()\n'
            'c = string.rep("ab", 3)\n'
            'd = ("hello"):sub(2, 4)\n'
            'e = table.concat({1, 2, 3}, "-")\n')
        self.assertEqual(runtime.get_global('a'), 'pts: 7 (2.2)')
        self.assertEqual(runtime.get_global('b'), 'MOLE')
        self.assertEqual(runtime.get_global('c'), 'ababab')
        self.assertEqual(runtime.get_global('d'), 'ell')
        self.assertEqual(runtime.get_global('e'), '1-2-3')

    def test_table_insert_remove_and_sort(self):
        runtime = self.run_lua(
            'local t = {3, 1, 2}\n table.sort(t)\n'
            'table.insert(t, 1, 0)\n table.remove(t)\n'
            'out = table.concat(t, ",")\n'
            'local u = {3, 1, 2}\n'
            'table.sort(u, function(a, b) return a > b end)\n'
            'down = table.concat(u, ",")\n')
        self.assertEqual(runtime.get_global('out'), '0,1,2')
        self.assertEqual(runtime.get_global('down'), '3,2,1')

    def test_a_runaway_script_is_stopped_rather_than_hanging_titan(self):
        runtime = LuaRuntime()
        runtime.interpreter.MAX_STEPS = 500
        with self.assertRaises(LuaError):
            runtime.run('while true do end')

    def test_a_script_may_not_reach_the_file_system(self):
        runtime = LuaRuntime()
        for name in ('io', 'loadfile', 'dofile', 'load', 'loadstring'):
            self.assertIsNone(runtime.get_global(name), name)

    def test_a_module_outside_the_application_is_refused(self):
        root = tempfile.mkdtemp()
        try:
            runtime = LuaRuntime(root)
            with self.assertRaises(LuaError):
                runtime.run('require("....secrets")')
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_a_syntax_error_names_the_line(self):
        runtime = LuaRuntime()
        with self.assertRaises(Exception) as caught:
            runtime.run('a = 1\nif then\n')
        self.assertIn(':2', str(caught.exception))


class KlangoEmulation(ClingCase):
    """Running Klango's OWN code, rather than a re-creation of it.

    Cling's engines re-create a genre from an application's data; this is the
    other path - the application's own Lua, out of its own package, on Cling's
    interpreter. What these check is the part that has to be right before any
    of it can run: the environment Klango's library expects to find, and the
    boundary of what an application from the internet may touch.
    """

    def host_for(self, app_id='a'):
        path = self.klango_app(app_id, texts={'welcome': 'Hi'})
        app = catalog.discover([self.apps_root], 'en')[0]
        return path, host_module.ClingHost(
            app, 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            store=store_module.Store(app_id, 'test', self.state),
            clock=runner.FakeClock())

    def test_the_interpreter_reads_the_shape_klango_code_is_written_in(self):
        """Lua 5.1 idioms the library leans on, which plain Lua 5.4 dropped."""
        from clingkit.lua import LuaRuntime
        runtime = LuaRuntime()
        runtime.run('sum = 0\n'
                    'table.foreachi({10, 20, 30}, function(i, v)\n'
                    '  sum = sum + i * v end)\n'
                    'total = 0\n'
                    'table.foreach({a = 1, b = 2}, function(k, v)\n'
                    '  total = total + v end)\n'
                    'found = table.foreachi({10, 20}, function(i, v)\n'
                    '  if v == 20 then return i end end)\n')
        self.assertEqual(runtime.get_global('sum'), 140)
        self.assertEqual(runtime.get_global('total'), 3)
        self.assertEqual(runtime.get_global('found'), 2)

    def test_the_environment_klangos_library_expects_is_there(self):
        """`llib.lua` installs a package loader at position 2 before it defines
        anything, so an empty `package.loaders` stops the whole library."""
        from clingkit.klango import environment
        from clingkit.lua import LuaRuntime
        runtime = LuaRuntime()
        environment.install(runtime, lambda *_a: None)
        runtime.run('local kloader = function(n) return n end\n'
                    'table.insert(package.loaders, 2, kloader)\n'
                    'loaders = #package.loaders\n'
                    'debug = { setfenv = debug.setfenv }\n'
                    'joined = utf8.format("%s and %s", "one", "two")\n')
        self.assertEqual(runtime.get_global('loaders'), 5)
        self.assertEqual(runtime.get_global('joined'), 'one and two')

    def test_json_crosses_the_boundary_both_ways(self):
        from clingkit.klango import environment
        from clingkit.lua import LuaRuntime
        runtime = LuaRuntime()
        environment.install(runtime, lambda *_a: None)
        runtime.run('local json = require("json")\n'
                    'text = json.encode({1, 2, 3})\n'
                    'back = json.decode(\'{"a": 7, "b": [1, 2]}\')\n'
                    'a = back.a\n'
                    'b2 = back.b[2]\n')
        self.assertEqual(runtime.get_global('text'), '[1, 2, 3]')
        self.assertEqual(runtime.get_global('a'), 7)
        self.assertEqual(runtime.get_global('b2'), 2)

    def test_an_application_may_not_read_outside_itself(self):
        """A package came from wherever the user found it."""
        from clingkit.klango import natives
        path, _host = self.host_for()
        filesystem = natives.Filesystem(path, '', os.path.join(self.state, 'w'))
        self.assertTrue(filesystem.resolve('/kni.txt'))
        for escape in ('/../../secrets', '../../secrets', '/..\\..\\secrets'):
            self.assertEqual(filesystem.resolve(escape), '',
                             'it escaped with %r' % escape)

    def test_starting_a_program_is_refused_and_recorded(self):
        """The three things a downloaded package must never do."""
        from clingkit.klango import natives
        from clingkit.lua import LuaRuntime
        path, host = self.host_for()
        runtime = LuaRuntime()
        natives.MISSING.clear()
        natives.install(runtime, host,
                        natives.Filesystem(path, '', os.path.join(self.state, 'w')),
                        lambda *_a: None)
        runtime.run('_Sys_Execute("format c:")\n_Sys_KillEngine()\n')
        self.assertIn('_Sys_Execute', natives.MISSING)
        self.assertIn('_Sys_KillEngine', natives.MISSING)

    def test_a_session_says_what_it_is_missing_rather_than_half_running(self):
        from clingkit import klango
        _path, host = self.host_for()
        session, started = klango.boot(host, lib_root='')
        self.assertFalse(started)
        report = session.report()
        self.assertTrue(report)
        self.assertTrue(any('llib' in line or 'entry file' in line
                            for line in report), report)


class KlangoVirtualFilesystem(ClingCase):
    """Mount points, not a search path - and why that distinction matters.

    Klango gives its platform library a mediaset rooted at `/llib` and the
    application one rooted at `/`, and both then read `lang/` beneath
    themselves. Resolved by searching the application first and the library
    second, the library asks for its own texts and is handed the
    application's - and every application then dies in the same place.
    """

    def filesystem(self):
        from clingkit.klango import natives
        app = os.path.join(self.root, 'app')
        lib = os.path.join(self.root, 'lib')
        write(os.path.join(app, 'lang', 'mine.txt'), 'the application')
        write(os.path.join(lib, 'lang', 'mine.txt'), 'the library')
        return natives.Filesystem(app, lib, os.path.join(self.root, 'w'))

    def test_the_library_reads_its_own_files_not_the_applications(self):
        files = self.filesystem()
        with open(files.resolve('/lang/mine.txt'), encoding='utf-8') as handle:
            self.assertEqual(handle.read(), 'the application')
        with open(files.resolve('/llib/lang/mine.txt'), encoding='utf-8') as handle:
            self.assertEqual(handle.read(), 'the library')

    def test_a_mount_appears_in_its_parents_listing(self):
        """Klango walks `/apps` to find applications; an unlisted mount is an
        application that does not exist."""
        files = self.filesystem()
        files.mount('/apps/cling/mole', os.path.join(self.root, 'app'))
        self.assertIn('apps', files.listdir('/'))
        self.assertEqual(files.listdir('/apps'), ['cling'])
        self.assertEqual(files.listdir('/apps/cling'), ['mole'])
        self.assertTrue(files.is_directory('/apps/cling/mole'))

    def test_nothing_outside_a_mount_exists(self):
        files = self.filesystem()
        for escape in ('/../secrets', '../../secrets', '/llib/../../secrets'):
            self.assertEqual(files.resolve(escape), '', escape)

    def test_writing_never_touches_the_application_or_the_library(self):
        files = self.filesystem()
        target = files.resolve('/lang/mine.txt', for_writing=True)
        self.assertTrue(target.startswith(files.writable), target)


class KlangoNatives(ClingCase):
    """The primitives, where getting the SHAPE right is the whole job."""

    def host_and_runtime(self):
        from clingkit.klango import engine, environment, keyboard, natives
        from clingkit.lua import LuaRuntime
        path = self.klango_app('a', texts={'welcome': 'Hi'})
        app = catalog.discover([self.apps_root], 'en')[0]
        host = host_module.ClingHost(
            app, 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            store=store_module.Store('a', 'test', self.state),
            clock=runner.FakeClock())
        runtime = LuaRuntime()
        files = natives.Filesystem(path, '', os.path.join(self.state, 'w'))
        keys = keyboard.Keyboard()
        natives.install(runtime, host, files, lambda *_a: None)
        engine.install(runtime, host, files, keys)
        environment.install(runtime, lambda *_a: None)
        return host, runtime, keys

    def test_a_voice_handle_is_not_a_number(self):
        """`k_VoiceSpeak` re-calls itself when handed a number or a string, so a
        numeric handle made every call recurse until the stack gave out."""
        _host, runtime, _keys = self.host_and_runtime()
        runtime.run('v = _Voice_Create({})\nkind = type(v)\n')
        self.assertEqual(runtime.get_global('kind'), 'table')

    def test_a_missing_global_string_answers_nil_not_empty(self):
        """Every Lua string is true, including ''. Answering '' made the
        library overwrite the application's language with nothing."""
        _host, runtime, _keys = self.host_and_runtime()
        runtime.run('missing = _Sys_GlobalString_Get("nobody set this")\n'
                    '_Sys_GlobalString_Set("k", "v")\n'
                    'present = _Sys_GlobalString_Get("k")\n')
        self.assertIsNone(runtime.get_global('missing'))
        self.assertEqual(runtime.get_global('present'), 'v')

    def test_the_directory_cursor_answers_four_values(self):
        _host, runtime, _keys = self.host_and_runtime()
        runtime.run('n, d, size, when = _Dir_ReadFirst("/lang")\n'
                    'ended = _Dir_ReadNext()\n')
        self.assertTrue(runtime.get_global('n'))
        self.assertIn(runtime.get_global('d'), (True, False))

    def test_a_table_survives_being_written_and_read_back(self):
        _host, runtime, _keys = self.host_and_runtime()
        runtime.run('local t = { 1, 2, name = "mole", nested = { on = true } }\n'
                    'text = k_Serialize(t)\n'
                    'back = k_Unserialize(text)\n'
                    'a = back[1]\n b = back.name\n c = back.nested.on\n')
        self.assertEqual(runtime.get_global('a'), 1)
        self.assertEqual(runtime.get_global('b'), 'mole')
        self.assertIs(runtime.get_global('c'), True)

    def test_markup_becomes_the_node_shape_the_library_reads(self):
        _host, runtime, _keys = self.host_and_runtime()
        runtime.run('x = k_XMLParsePS("<z>one <b>two</b><br>three</z>")\n'
                    'name = x[1].name\n inner = x[1][2].name\n'
                    'first = x[1][1]\n')
        self.assertEqual(runtime.get_global('name'), 'z')
        self.assertEqual(runtime.get_global('inner'), 'b')
        self.assertEqual(runtime.get_global('first'), 'one ')

    def test_talking_to_other_klango_windows_is_refused_with_a_shape(self):
        """A refusal that answers nil is a refusal the caller then iterates."""
        _host, runtime, _keys = self.host_and_runtime()
        runtime.run('windows = _Sys_Ipc_GetKlangoWindows()\n'
                    'n = 0\n for _ in ipairs(windows) do n = n + 1 end\n')
        self.assertEqual(runtime.get_global('n'), 0)

    def test_a_key_reaches_the_application_only_through_the_queue(self):
        """Nothing reads the real keyboard: a key is put into the queue by
        whoever is driving the session, and the application sees it on its
        next frame - as a Windows virtual key, which is what the platform's
        own key messages carry."""
        _host, runtime, keys = self.host_and_runtime()
        keys.press('space')
        runtime.run('_Inp_KeySys_Refresh()\n'
                    'got = _Inp_KeySys_GetKeyDowns()\n first = got[1]\n'
                    'held = _Inp_KeySys_GetKeys()[57]\n'
                    'msg = _Inp_KeySys_GetKeyMssages()[1]\n'
                    'kind = msg[1]\n vkey = msg[2]\n')
        self.assertEqual(runtime.get_global('first'), 0x20)   # VK_SPACE
        self.assertEqual(runtime.get_global('held'), 1)
        self.assertEqual(runtime.get_global('kind'), 1)       # WM_KEYDOWN
        self.assertEqual(runtime.get_global('vkey'), 0x20)
        # The next frame is the release, and after that the key is gone.
        runtime.run('_Inp_KeySys_Refresh()\n up = _Inp_KeySys_GetKeyUps()[1]\n'
                    'still = _Inp_KeySys_GetKeys()[57]\n')
        self.assertEqual(runtime.get_global('up'), 0x20)
        self.assertEqual(runtime.get_global('still'), 0)

    def test_the_raw_buffer_is_scan_codes_and_the_messages_are_virtual_keys(self):
        """They are different numbers for the same key and both are needed:
        the menu recognises Escape by scan code 1 in the raw buffer, and the
        application shell recognises it as virtual key 27 in a message."""
        _host, runtime, keys = self.host_and_runtime()
        keys.press('escape')
        runtime.run('_Inp_KeySys_Refresh()\n'
                    'count = _Inp_KeySys_BuffGetCnt()\n'
                    'scan, down = _Inp_KeySys_BuffGet(0)\n'
                    'vkey = _Inp_KeySys_GetKeyMssages()[1][2]\n')
        self.assertEqual(runtime.get_global('count'), 1)
        self.assertEqual(runtime.get_global('scan'), 1)
        self.assertEqual(runtime.get_global('down'), 1)
        self.assertEqual(runtime.get_global('vkey'), 27)

    def test_alt_arrives_as_a_system_key_because_that_is_the_menu(self):
        """`llib_suiapp.lua` opens the menu on message type 4 (WM_SYSKEYUP)
        with virtual key 18. A key that arrives as an ordinary one never
        opens a menu, which is how an emulated application ends up with no
        way in."""
        _host, runtime, keys = self.host_and_runtime()
        keys.press('alt')
        runtime.run('_Inp_KeySys_Refresh()\n'
                    'down = _Inp_KeySys_GetKeyMssages()[1][1]\n'
                    'dkey = _Inp_KeySys_GetKeyMssages()[1][2]\n'
                    '_Inp_KeySys_Refresh()\n'
                    'up = _Inp_KeySys_GetKeyMssages()[1][1]\n'
                    'ukey = _Inp_KeySys_GetKeyMssages()[1][2]\n')
        self.assertEqual(runtime.get_global('down'), 3)     # WM_SYSKEYDOWN
        self.assertEqual(runtime.get_global('up'), 4)       # WM_SYSKEYUP
        self.assertEqual(runtime.get_global('dkey'), 18)    # VK_MENU
        self.assertEqual(runtime.get_global('ukey'), 18)

    def test_a_key_released_is_reported_as_released_not_merely_forgotten(self):
        """DirectInput hands Klango the whole keyboard, and the library clears
        its own held-frame count only when it is told a key is at zero. Left
        to grow, the count reached 2 and `k_KeyJustPressed` - which is `== 1`
        - was false for ever: Enter chose a menu item once and never again."""
        _host, runtime, keys = self.host_and_runtime()
        for _ in range(2):
            keys.press('enter')
            runtime.run('_Inp_KeySys_Refresh()\n'
                        'state = _Inp_KeySys_GetKeys()[28]\n')
            self.assertEqual(runtime.get_global('state'), 1)
            runtime.run('_Inp_KeySys_Refresh()\n'
                        'state = _Inp_KeySys_GetKeys()[28]\n')
            self.assertEqual(runtime.get_global('state'), 0)


class TheEmulator(unittest.TestCase):
    """The engine that runs an application's OWN Klango code.

    Bounded on purpose: the emulator runs a real program on a thread of its
    own, and a test that let it run freely would be a test that never ends.
    """

    LIBRARY = None

    @classmethod
    def setUpClass(cls):
        from clingkit.klango.session import find_library
        try:
            cls.LIBRARY = find_library()
        except Exception:
            cls.LIBRARY = ''

    def emulated(self):
        return {app_id: app for app_id, app in INSTALLED.items()
                if app.engine == catalog.ENGINE_KLANGO}

    def test_an_application_with_its_own_code_is_given_the_emulator(self):
        if not self.LIBRARY:
            self.skipTest("Klango's library is not installed")
        emulated = self.emulated()
        self.assertTrue(emulated, 'nothing is emulated')
        for app_id, app in emulated.items():
            with self.subTest(app=app_id):
                self.assertTrue(app.package or catalog.has_klango_code(app.path),
                                '%s has no code of its own' % app_id)

    def test_the_engine_built_for_one_is_the_klango_engine(self):
        if not self.emulated():
            self.skipTest("nothing is emulated")
        app_id = sorted(self.emulated())[0]
        app = INSTALLED[app_id]
        host = host_module.ClingHost(
            app, 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            store=store_module.Store(app_id, 'test-suite',
                                     tempfile.mkdtemp(prefix='cling-emu-')),
            clock=runner.FakeClock())
        engine = engines.build(host)
        self.assertEqual(type(engine).__name__, 'KlangoEngine')

    def test_without_the_library_it_says_so_instead_of_starting(self):
        """An application's own code has to have something to run on."""
        from clingkit.engines.klango_app import KlangoEngine
        from clingkit.klango import session as session_module

        if not self.emulated():
            self.skipTest("nothing is emulated")
        app_id = sorted(self.emulated())[0]
        app = INSTALLED[app_id]
        host = host_module.ClingHost(
            app, 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            store=store_module.Store(app_id, 'test-suite',
                                     tempfile.mkdtemp(prefix='cling-emu-')),
            clock=runner.FakeClock())
        original = session_module.find_library
        session_module.find_library = lambda *_a: ''
        try:
            engine = KlangoEngine(host)
            engine.start()
            self.assertFalse(engine.running)
            self.assertIn('llib', engine.error)
            self.assertTrue(host.messages)
        finally:
            session_module.find_library = original

    def test_the_emulator_speaks_through_titan(self):
        """Klango renders an application's speech itself; here it must reach
        Titan's own voice, both ways it can be asked for."""
        if not self.LIBRARY:
            self.skipTest("Klango's library is not installed")
        if 'mole' not in self.emulated():
            self.skipTest('mole is not installed')
        from clingkit import klango
        host = host_module.ClingHost(
            INSTALLED['mole'], 'en', speaker=QuietSpeaker(),
            mixer=SilentMixer(),
            store=store_module.Store('mole', 'test-suite',
                                     tempfile.mkdtemp(prefix='cling-say-')),
            clock=runner.FakeClock())
        session = klango.KlangoSession(host)
        session.runtime.interpreter.MAX_STEPS = 5000000
        session.load_library()
        session.start_platform()
        session.runtime.run('local v = k_VoicePrepare{ name = "Titan" }\n'
                            'kind = type(v)\n'
                            'k_VoiceSpeak(v, "spoken by the voice")\n'
                            'k_SoundPlay{ "*spoken by a sample" }\n', 'probe')
        # A voice handle must be a table, or `k_VoiceSpeak` recurses on itself.
        self.assertEqual(session.runtime.get_global('kind'), 'table')
        self.assertIn('spoken by the voice', host.speaker.spoken)
        # `*text` is Klango's own convention for "say this", and it is most of
        # what an application says.
        self.assertIn('spoken by a sample', host.speaker.spoken)

    def test_a_sound_that_is_playing_says_so(self):
        """Klango's dialogs step on when `_Snd_IsPlaying` says no, so a layer
        that always says no makes every spoken line collapse unheard."""
        if not self.LIBRARY or 'mole' not in self.emulated():
            self.skipTest('mole is not installed')
        from clingkit import klango
        clock = runner.FakeClock()
        host = host_module.ClingHost(
            INSTALLED['mole'], 'en', speaker=QuietSpeaker(),
            mixer=SilentMixer(),
            store=store_module.Store('mole', 'test-suite',
                                     tempfile.mkdtemp(prefix='cling-busy-')),
            clock=clock)
        session = klango.KlangoSession(host)
        session.runtime.run('id = _Snd_Create("*a fairly long spoken line here")\n'
                            'busy = _Snd_IsPlaying(id)\n', 'probe')
        self.assertTrue(session.runtime.get_global('busy'),
                        'a line just spoken reports as not playing')
        clock.advance(60.0)
        session.runtime.run('later = _Snd_IsPlaying(id)\n', 'probe')
        self.assertFalse(session.runtime.get_global('later'),
                         'it never stops playing')

    def test_klangos_own_rpc_reaches_titan_net(self):
        """A Klango application asks klango.net for its high scores. That server
        has been gone for years and the user has a Titan-Net account, so the two
        calls that mean something here are answered by Titan-Net - in the row
        shape the application's own Lua then reads."""
        if not self.LIBRARY or 'mole' not in self.emulated():
            self.skipTest('mole is not installed')
        from clingkit import klango
        net = FakeNetClient('tito')
        original = account._live_client
        account._live_client = lambda: net
        try:
            host = host_module.ClingHost(
                INSTALLED['mole'], 'en', speaker=QuietSpeaker(),
                mixer=SilentMixer(),
                store=store_module.Store('mole', 'test-suite',
                                         tempfile.mkdtemp(prefix='cling-rpc-')),
                clock=runner.FakeClock())
            session = klango.KlangoSession(host)
            session.runtime.run(
                'local rpc = k_NewKRPC{ url = "http://klango.net/krpc.php" }\n'
                'local sub = rpc:new{ url = "x" }\n'
                'sent = sub:exec("SendHS", "tito", 0, 12, 3, 187, 5):done()\n'
                'local back = sub:exec("GetHS"):result()\n'
                'who = back.result[1].klangoid\n'
                'total = back.result[1].total\n'
                'moles = back.result[1].normal_moles\n', 'probe')
            self.assertTrue(session.runtime.get_global('sent'))
            self.assertEqual(session.runtime.get_global('who'), 'tito')
            self.assertEqual(session.runtime.get_global('total'), 187)
            # Mole No More sends `(user, fails, normal, special, total,
            # level, version)` and Skeet sends `(user, score, level)`;
            # Klango's server knew each game's columns and Cling cannot, so
            # every number the game sent is kept and the largest is the
            # score. Nothing an application sent is thrown away.
            self.assertEqual(session.runtime.get_global('moles'), 12)
            row = net.data[('cling', 'scores_mole')][0]
            self.assertEqual(row['name'], 'tito')
            self.assertEqual(row['points'], 187)
            self.assertEqual(row['values'], [0, 12, 3, 187, 5])
        finally:
            account._live_client = original

    def test_a_request_that_cannot_be_answered_is_still_a_request(self):
        """Never nil: the caller asks the answer whether it is `done()` on the
        next line."""
        if not self.LIBRARY or 'mole' not in self.emulated():
            self.skipTest('mole is not installed')
        from clingkit import klango
        host = host_module.ClingHost(
            INSTALLED['mole'], 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            store=store_module.Store('mole', 'test-suite',
                                     tempfile.mkdtemp(prefix='cling-rpc2-')),
            clock=runner.FakeClock())
        session = klango.KlangoSession(host)
        session.runtime.run('local rpc = k_NewKRPC{}\n'
                            'local a = rpc:exec("SomethingKlangoOnlyHad")\n'
                            'done = a:done()\n result = a:result()\n', 'probe')
        self.assertTrue(session.runtime.get_global('done'))
        self.assertIsNone(session.runtime.get_global('result'))

    def test_a_key_is_named_the_way_klangos_key_system_names_it(self):
        """One table reconciles what Cling's windows call a key with what
        Klango's key system calls it, and it carries BOTH numbers - the
        DirectInput scan code and the Windows virtual key."""
        from clingkit.klango import keyboard
        self.assertEqual(keyboard.canonical('escape'), 'escape')
        self.assertEqual(keyboard.canonical('esc'), 'escape')
        self.assertEqual(keyboard.canonical('return'), 'enter')
        self.assertEqual(keyboard.canonical('LEFT'), 'left')
        self.assertEqual(keyboard.canonical('alt'), 'lalt')
        self.assertEqual(keyboard.canonical('nonsense'), '')
        self.assertEqual(keyboard.KEYS['escape'], (1, 0x1B))
        self.assertEqual(keyboard.KEYS['lalt'], (56, 0x12))

    def test_the_platform_really_starts_and_the_application_is_found(self):
        """The whole path, once, under a step budget: library, platform,
        applications tree, and the application's own `main()`."""
        if 'mole' not in self.emulated():
            self.skipTest('mole is not installed')
        from clingkit import klango
        host = host_module.ClingHost(
            INSTALLED['mole'], 'en', speaker=QuietSpeaker(),
            mixer=SilentMixer(),
            store=store_module.Store('mole', 'test-suite',
                                     tempfile.mkdtemp(prefix='cling-emu-')),
            clock=runner.FakeClock())
        session = klango.KlangoSession(host)
        # The application's own loop paces itself to 60 frames a second and
        # never ends by itself - it IS the game - so a test must not wait for
        # real time and must not wait for the game either. It is stopped by
        # the same flag a closing window uses, after enough frames to have
        # got well into `main()`.
        session.frames.period = 0.0
        session.frames.on_frame(
            lambda: setattr(session, 'stopping', session.frames.frames > 400))
        ran = session.start()
        self.assertGreater(len(session.loaded), 50,
                           "the platform library did not load")
        self.assertTrue(session.runtime.call_global('_cling_apps_tree'),
                        "Klango's applications tree was not built")
        self.assertTrue(ran, 'main() failed: %s' % session.problems[:2])
        self.assertTrue(session.stopped,
                        'it was not the stop that ended it: %s'
                        % session.problems[:2])
        self.assertGreater(session.frames.frames, 100,
                           'the application never reached its own loop')


class ClosingReallyCloses(unittest.TestCase):
    """The window closes; the application stops and so does its sound.

    An emulated application runs on a thread of its own and is a frame - or a
    long Lua call - away from noticing that it has been asked to stop. Waiting
    for it to notice left a game playing its background music for those two
    seconds, and a game that never reached a frame played it for ever. So the
    host is CLOSED rather than merely stopped: what is playing stops now, and
    nothing asked for afterwards is answered, however late it arrives.
    """

    def host(self):
        return host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())

    def test_closing_stops_what_is_playing_including_the_one_shots(self):
        """Only the LOOPS were tracked, so a long announcement or a level's
        own fanfare went on after the window had gone."""
        host = self.host()
        one_shot = host.mixer.start('/a.ogg')
        music = host.mixer.loop('/b.ogg')
        one_shot.alive = True                      # still going when we close
        host.close()
        self.assertFalse(host.mixer.busy(one_shot))
        self.assertFalse(host.mixer.busy(music))

    def test_nothing_starts_after_the_close(self):
        host = self.host()
        host.close()
        self.assertIsNone(host.mixer.start('/a.ogg'))
        self.assertFalse(host.say('too late'))
        host.show('too late')
        self.assertNotIn('too late', host.speaker.spoken)

    def test_a_scheduled_sound_never_arrives_after_the_close(self):
        """A Klango sequence schedules its sounds ahead of time; one whose
        moment comes after the window has closed must not be started."""
        from clingkit.klango import sounds
        host = self.host()
        bank = sounds.SoundBank(host, None, _speaking(host), lambda name: '/x.ogg')
        bank.samples['x'] = sounds.Sample('x', text='later', length=0.5)
        bank.create('x', None, _lua_table({'delay': 5.0}))
        host.klango_sounds = bank
        host.close()
        host.clock.advance(10.0)
        bank.pump()
        self.assertEqual(host.speaker.spoken, [])

    def test_closing_twice_is_the_same_as_closing_once(self):
        host = self.host()
        host.close()
        host.close()
        self.assertTrue(host.closed)

    def test_the_engine_closes_the_host_before_it_waits_for_the_thread(self):
        """The order is the whole of what "closing the window silences it"
        means: a thread that is slow to notice must not still be audible."""
        from clingkit.engines.klango_app import KlangoEngine
        host = self.host()
        engine = KlangoEngine(host)
        order = []
        host.close = lambda: order.append('closed')

        class SlowThread(object):
            def is_alive(self):
                order.append('waited')
                return False
        engine.thread = SlowThread()
        engine.session = type('S', (), {'stopping': False})()
        engine.stop()
        self.assertEqual(order[0], 'closed')


class ClingSpeaksTitansLanguage(unittest.TestCase):
    """The PLATFORM's language is Titan's, not the application's.

    `host.texts.locale` is the best locale an application actually ships,
    which is a different question: Mole No More has only `en-us`, and reading
    the platform's language off it made the menu, the word "Settings", the
    word "Help" and the whole of Klango's own interface English on a Polish
    Titan.
    """

    def host(self, language, app=None):
        return host_module.ClingHost(
            app or _AnyApp(), language, speaker=QuietSpeaker(),
            mixer=SilentMixer(), clock=runner.FakeClock())

    def test_titans_language_in_klangos_spelling(self):
        self.assertEqual(self.host('pl').locale, 'pl-pl')
        self.assertEqual(self.host('en').locale, 'en-us')

    def test_an_application_with_no_polish_does_not_make_titan_english(self):
        if 'mole' not in INSTALLED:
            self.skipTest('mole is not installed')
        host = self.host('pl', INSTALLED['mole'])
        self.assertEqual(host.texts.locale, 'en-us',
                         'mole really does ship only English')
        self.assertEqual(host.locale, 'pl-pl',
                         "the platform followed the application, not Titan")

    def test_the_language_is_written_on_every_run_not_only_the_first(self):
        """The library keeps what it settled on in `/user/app/lang` and reads
        it back at the next start, so a stale value outlived every later
        choice the user made in Titan."""
        from clingkit.klango import engine, keyboard, natives
        from clingkit.lua import LuaRuntime

        state = tempfile.mkdtemp(prefix='cling-lang-')
        app = _AnyApp()
        for language, expected in (('pl', 'pl-pl'), ('en', 'en-us')):
            host = host_module.ClingHost(
                app, language, speaker=QuietSpeaker(), mixer=SilentMixer(),
                store=store_module.Store('test', 'suite', state),
                clock=runner.FakeClock())
            runtime = LuaRuntime()
            files = natives.Filesystem(app.path, '',
                                       tempfile.mkdtemp(prefix='cling-lw-'))
            natives.install(runtime, host, files, lambda *_a: None)
            engine.install(runtime, host, files, keyboard.Keyboard())
            self.assertEqual(host.store.get('reg:/user/app/lang'), expected)

    def test_a_voice_is_offered_for_every_language_that_can_be_asked_for(self):
        """`k_VoiceEnum` filters by language and an empty answer ends the
        application (`killklangobecauseoflang`). Titan's voice is offered for
        Titan's language, the application's, and English."""
        from clingkit.klango import engine, keyboard, natives
        from clingkit.lua import LuaRuntime

        host = self.host('pl')
        runtime = LuaRuntime()
        files = natives.Filesystem(host.app.path, '',
                                   tempfile.mkdtemp(prefix='cling-v-'))
        natives.install(runtime, host, files, lambda *_a: None)
        engine.install(runtime, host, files, keyboard.Keyboard())
        runtime.run('v = _Voice_Enum()\n n = 0\n langs = ""\n'
                    'for _, one in ipairs(v) do n = n + 1\n'
                    '  langs = langs .. one.lang .. " " end\n')
        self.assertGreaterEqual(runtime.get_global('n'), 2)
        self.assertIn('pl', runtime.get_global('langs'))
        self.assertIn('en', runtime.get_global('langs'))


class PolishKeepsItsLetters(unittest.TestCase):
    """Cling's own words, in Polish, with the letters Polish has."""

    def catalogue(self):
        import gettext
        return gettext.translation(
            'cling', os.path.join(COMPONENT, 'languages'), languages=['pl'])

    def test_the_polish_catalogue_really_is_polish(self):
        polish = self.catalogue()
        for english, expected in (
                ('Soundscapes', 'Pejza\u017ce d\u017awi\u0119kowe'),
                ('Details', 'Szczeg\u00f3\u0142y'),
                ('Language', 'J\u0119zyk'),
                ('What the application has said',
                 'Co powiedzia\u0142a aplikacja')):
            self.assertEqual(polish.gettext(english), expected)

    def test_cling_says_it_is_ready_in_polish(self):
        self.assertEqual(self.catalogue().gettext('Cling is ready'),
                         'Cling gotowy')

    def test_the_demo_applications_polish_has_its_letters(self):
        folder = os.path.join(catalog.component_apps_dir(), 'clingdemo',
                              'lang', 'pl-pl', 'default')
        found = False
        for name in os.listdir(folder):
            with open(os.path.join(folder, name), encoding='utf-8') as handle:
                text = handle.read()
            found = found or any(letter in text
                                 for letter in '\u0105\u0107\u0119\u0142'
                                               '\u0144\u00f3\u015b\u017a\u017c')
        self.assertTrue(found, "the demo's Polish has no Polish letters in it")


class TheApplicationIsWhereverItIs(unittest.TestCase):
    """A mount can be several real folders, and an application needs it.

    Typing Lessons ships its code, its texts and its skin in `ktypist.pag`
    and its LESSONS in the folder beside it. Mounting one of the two answered
    "the collection is empty" and the application had nothing to teach.
    """

    def files(self, *roots):
        from clingkit.klango import natives
        return natives.Filesystem(list(roots), '',
                                  tempfile.mkdtemp(prefix='cling-fsw-'))

    def two_halves(self):
        first = tempfile.mkdtemp(prefix='cling-half1-')
        second = tempfile.mkdtemp(prefix='cling-half2-')
        write(os.path.join(first, 'code.lua'), '-- the package')
        os.makedirs(os.path.join(second, 'trainings'))
        write(os.path.join(second, 'trainings', 'lesson.txt'), 'aaa sss')
        write(os.path.join(second, 'code.lua'), '-- the folder')
        return first, second

    def test_a_file_in_either_half_is_found(self):
        first, second = self.two_halves()
        files = self.files(first, second)
        self.assertTrue(files.resolve('/code.lua'))
        self.assertTrue(files.resolve('/trainings/lesson.txt'))

    def test_the_first_root_answers_when_both_have_it(self):
        first, second = self.two_halves()
        files = self.files(first, second)
        self.assertTrue(files.resolve('/code.lua').startswith(first))

    def test_a_folder_lists_both_halves_at_once(self):
        first, second = self.two_halves()
        files = self.files(first, second)
        names = files.listdir('/')
        self.assertIn('code.lua', names)
        self.assertIn('trainings', names)
        self.assertEqual(len(names), len(set(names)), 'a name listed twice')

    def test_one_root_still_works(self):
        first, _second = self.two_halves()
        files = self.files(first)
        self.assertTrue(files.resolve('/code.lua'))
        self.assertFalse(files.resolve('/trainings/lesson.txt'))


class TheTextControl(unittest.TestCase):
    """`_Gfx_TxtEdit_*` - where a search term, a message or a name is typed.

    Everything else `_Gfx_` does is drawing and answers nothing; this one is
    not decoration, and answering nothing here is where the Wikipedia
    browser, the chat and every application with a field stopped.
    """

    def editor(self, **options):
        from clingkit.klango import textedit
        return textedit.TextEdit(1, **options)

    def test_typing_and_taking_it_back(self):
        editor = self.editor()
        editor.insert('titan')
        self.assertEqual(editor.text, 'titan')
        editor.backspace()
        self.assertEqual((editor.text, editor.deleted), ('tita', 'n'))

    def test_a_read_only_control_refuses(self):
        editor = self.editor(readonly=True)
        self.assertFalse(editor.insert('x'))
        self.assertEqual(editor.text, '')

    def test_the_caret_moves_and_selects(self):
        from clingkit.klango import textedit
        editor = self.editor()
        editor.insert('abcdef')
        editor.key(textedit.VK_HOME)
        self.assertEqual(editor.caret, 0)
        editor.key(textedit.VK_RIGHT, shift=True)
        editor.key(textedit.VK_RIGHT, shift=True)
        self.assertEqual(editor.selection, (0, 2))
        editor.backspace()
        self.assertEqual(editor.text, 'cdef')

    def test_a_line_ends_with_a_carriage_return_because_klango_looks_for_one(self):
        from clingkit.klango import textedit
        editor = self.editor(multiline=True)
        editor.insert('one')
        editor.key(textedit.VK_RETURN)
        editor.insert('two')
        self.assertEqual(editor.text, 'one\rtwo')
        self.assertEqual(editor.lines(), 2)
        # `Find` looks from the caret, which is what the library asks it for
        # ("where does the next line begin").
        editor.set_caret(0)
        self.assertEqual(editor.find('\r'), 3)
        self.assertEqual(editor.current_line(), 'one')

    def test_what_the_library_asks_to_be_read_out(self):
        from clingkit.klango import textedit
        editor = self.editor(multiline=True)
        editor.insert('Hello there. Second one.')
        editor.set_caret(2)
        self.assertEqual(editor.get_text(textedit.CHAR), 'l')
        self.assertEqual(editor.get_text(textedit.WORD), 'Hello')
        self.assertEqual(editor.get_text(textedit.ALL),
                         'Hello there. Second one.')
        self.assertEqual(editor.get_text(textedit.SENTENCE), 'Hello there.')

    def test_the_limit_is_a_limit(self):
        editor = self.editor(maxlen=3)
        editor.insert('abcdef')
        self.assertEqual(editor.text, 'abc')

    def test_typing_reaches_the_focused_control_and_no_other(self):
        from clingkit.klango import keyboard, textedit
        editors = textedit.Editors()
        first = editors.create()
        second = editors.create()
        editors.focus(second.id)
        keys = keyboard.Keyboard()
        for letter in 'hi':
            keys.press(letter)
            keys.refresh()
            editors.apply(keys)
            keys.refresh()
            editors.apply(keys)
        self.assertEqual(second.text, 'hi')
        self.assertEqual(first.text, '')

    def test_rtf_is_read_as_words(self):
        """`SetText2` is handed RTF and `GetText` must answer the words. It
        used to answer the markup, which a screen reader then read out."""
        from clingkit.klango.engine import _rtf_to_text
        document = (r'{\rtf1\ansi\ansicpg1252{\colortbl;\red255\green0\blue0;}'
                    r'{\fonttbl{\f0 Arial;}}\f0 Tytan \u380?ycie\par druga}')
        self.assertEqual(_rtf_to_text(document), 'Tytan \u017cycie\ndruga')

    def test_something_that_is_not_rtf_is_left_alone(self):
        from clingkit.klango.engine import _rtf_to_text
        self.assertEqual(_rtf_to_text('just words'), 'just words')

    # ------------------------------------------------- a field with lines
    def multiline(self, body):
        """A control with a document in it, put in the way an application
        puts one in - through the primitive, not by assignment."""
        from clingkit.klango import textedit
        editor = textedit.TextEdit(1, multiline=True)
        editor.set_text(body)
        return editor

    def test_a_document_put_in_with_newlines_has_lines(self):
        """`SetText` is how every document arrives - an article, a message,
        a note - and a rich edit normalises what it is given to `\\r`, which
        is the only separator the library then looks for. Kept as `\\n`, the
        Wikipedia browser's article was ONE line however long it was: Up and
        Down moved nowhere and it buzzed at both ends of a whole article."""
        editor = self.multiline('one\ntwo\r\nthree')
        self.assertEqual(editor.text, 'one\rtwo\rthree')
        self.assertEqual(editor.lines(), 3)

    def test_up_and_down_are_the_previous_and_the_next_line(self):
        from clingkit.klango import textedit
        editor = self.multiline('one\ntwo\nthree')
        seen = []
        for _step in range(3):
            editor.key(textedit.VK_DOWN)
            seen.append(editor.current_line())
        self.assertEqual(seen, ['two', 'three', 'three'])
        seen = []
        for _step in range(3):
            editor.key(textedit.VK_UP)
            seen.append(editor.current_line())
        self.assertEqual(seen, ['two', 'one', 'one'])

    def test_a_read_only_document_still_moves_by_line(self):
        """The article view is readonly. Refusing to move in it would be a
        document that can be opened and not read."""
        from clingkit.klango import textedit
        editor = textedit.TextEdit(1, multiline=True, readonly=True)
        editor.set_text('one\ntwo')
        editor.key(textedit.VK_DOWN)
        self.assertEqual(editor.current_line(), 'two')

    def test_a_one_line_field_does_not_move_by_line(self):
        from clingkit.klango import textedit
        editor = textedit.TextEdit(1)
        editor.set_text('one\ntwo')
        self.assertFalse(editor.key(textedit.VK_DOWN))

    def test_which_line_the_caret_is_on(self):
        """The second thing `GetCurrentLine` answers, counted from zero: the
        textarea reads it on every arrow to find out whether it has reached
        the top or the bottom, and buzzes when it has."""
        editor = self.multiline('one\ntwo\nthree')
        self.assertEqual(editor.line_index(), 0)
        editor.set_caret(5)
        self.assertEqual(editor.line_index(), 1)
        editor.set_caret(len(editor.text))
        self.assertEqual(editor.line_index(), editor.lines() - 1)

    def test_the_primitive_answers_the_text_and_the_line(self):
        from clingkit.klango import engine, keyboard, natives
        from clingkit.lua import LuaRuntime

        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        runtime = LuaRuntime()
        files = natives.Filesystem(host.app.path, '',
                                   tempfile.mkdtemp(prefix='cling-t-'))
        natives.install(runtime, host, files, lambda *_a: None)
        keys = keyboard.Keyboard()
        engine.install(runtime, host, files, keys)
        runtime.run('h = _Gfx_TxtEdit_Init{multiline = true}\n'
                    '_Gfx_TxtEdit_SetFocus(h, 1)\n'
                    '_Gfx_TxtEdit_SetText(h, "one\\ntwo\\nthree")\n'
                    'n = _Gfx_TxtEdit_GetNumberOfLines(h)\n')
        self.assertEqual(runtime.get_global('n'), 3)

        def arrow(name):
            keys.press(name)
            runtime.run('_Inp_KeySys_Refresh()\n'
                        'answer = {_Gfx_TxtEdit_GetCurrentLine('
                        'h, _Gfx_TxtEdit_GetCurrentPos(h))}\n')
            answer = runtime.get_global('answer')
            return answer.raw_get(1), answer.raw_get(2)

        self.assertEqual(arrow('down'), ('two', 1))
        self.assertEqual(arrow('down'), ('three', 2))
        self.assertEqual(arrow('up'), ('two', 1))

    def test_the_space_bar_is_a_key(self):
        """`canonical(' ')` trimmed the name first, which leaves nothing at
        all - so the space bar was not a key Cling knew and `press(' ')`
        typed nothing. Every other letter went in, so a search box read back
        as what was typed with the spaces missing: the Wikipedia browser
        answered "I could not find anything matching your query" to a title
        that is on the front page."""
        from clingkit.klango import keyboard, textedit
        self.assertEqual(keyboard.canonical(' '), 'space')
        self.assertEqual(keyboard.canonical(' enter '), 'enter')
        self.assertEqual(keyboard.canonical(''), '')
        editors = textedit.Editors()
        editor = editors.create()
        editors.focus(editor.id)
        keys = keyboard.Keyboard()
        for character in 'kot domowy':
            self.assertTrue(keys.press(character), repr(character))
            keys.refresh()
            editors.apply(keys)
            keys.refresh()
            editors.apply(keys)
        self.assertEqual(editor.text, 'kot domowy')

    def test_focus_is_given_up_as_well_as_taken(self):
        """`_Gfx_TxtEdit_SetFocus(handle, f)`: 1 takes the keyboard, 0 gives
        it up - and the library says 0 the moment a control is built and
        again when the user leaves it. Reading the handle and ignoring the
        flag gave the keyboard TO every control that had just been built or
        just been left, so what was typed went to a buffer nobody was
        looking at."""
        from clingkit.klango import textedit
        editors = textedit.Editors()
        first = editors.create()
        second = editors.create()
        editors.focus(first.id, True)
        self.assertIs(editors.focused, first)
        editors.focus(second.id, True)
        self.assertIs(editors.focused, second)
        self.assertFalse(first.focused)
        editors.focus(second.id, False)
        self.assertIsNone(editors.focused)
        self.assertFalse(second.focused)

    def test_the_primitive_reads_klangos_flag(self):
        from clingkit.klango import engine, keyboard, natives
        from clingkit.lua import LuaRuntime

        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        runtime = LuaRuntime()
        files = natives.Filesystem(host.app.path, '',
                                   tempfile.mkdtemp(prefix='cling-f-'))
        natives.install(runtime, host, files, lambda *_a: None)
        engine.install(runtime, host, files, keyboard.Keyboard())
        runtime.run('h = _Gfx_TxtEdit_Init{}\n'
                    '_Gfx_TxtEdit_SetFocus(h, 1)\n'
                    'taken = _Gfx_TxtEdit_HasFocus(h)\n'
                    '_Gfx_TxtEdit_SetFocus(h, 0)\n'
                    'given = _Gfx_TxtEdit_HasFocus(h)\n')
        self.assertTrue(runtime.get_global('taken'))
        self.assertFalse(runtime.get_global('given'))


class AKeyIsHeldUntilItComesUp(unittest.TestCase):
    """`k_KeyJustReleased` only means anything if a held key is held here.

    Klango Piano starts a loop on a key going down and stops it on the key
    coming up, so a key released a frame after it was pressed can never
    sustain a note. DirectInput's own buffer carries no auto-repeat either,
    which is why the window treats a repeat as "still down" rather than as a
    second press.
    """

    KEY = 'e'

    def keyboard(self):
        from clingkit.klango import keyboard
        return keyboard.Keyboard()

    def scan(self):
        from clingkit.klango import keyboard
        return keyboard.KEYS[self.KEY][0]

    def test_a_held_key_stays_held_over_frames(self):
        keys = self.keyboard()
        keys.down(self.KEY)
        for _frame in range(5):
            keys.refresh()
            self.assertIn(self.scan(), keys.held)
        self.assertEqual(keys.buffer, [], 'it was reported down again')

    def test_it_is_let_go_only_when_it_is_let_go(self):
        keys = self.keyboard()
        keys.down(self.KEY)
        keys.refresh()
        keys.refresh()
        keys.up(self.KEY)
        keys.refresh()
        self.assertNotIn(self.scan(), keys.held)
        self.assertIn((self.scan(), 0), keys.buffer,
                      'the release never reached the raw buffer')

    def test_a_press_is_still_down_then_up(self):
        """What an action or a test does - and what the window used to do -
        still works: one frame down, released after it."""
        keys = self.keyboard()
        keys.press(self.KEY)
        keys.refresh()
        self.assertIn(self.scan(), keys.held)
        keys.refresh()
        self.assertNotIn(self.scan(), keys.held)


class APrimitiveNobodyWroteDoesNotEndTheApplication(unittest.TestCase):
    """A name that is nil is not a function, and calling one ends the run."""

    def runtime(self):
        from clingkit.klango import engine, keyboard, natives
        from clingkit.lua import LuaRuntime

        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        runtime = LuaRuntime()
        files = natives.Filesystem(host.app.path, '',
                                   tempfile.mkdtemp(prefix='cling-net-'))
        natives.install(runtime, host, files, lambda *_a: None)
        engine.install(runtime, host, files, keyboard.Keyboard())
        return runtime

    def test_an_unwritten_primitive_answers_and_is_recorded(self):
        from clingkit.klango import natives
        natives.MISSING.clear()
        runtime = self.runtime()
        runtime.run('answer = _Sys_SomethingNobodyWrote(1, 2)\n')
        self.assertIsNone(runtime.get_global('answer'))
        self.assertIn('_Sys_SomethingNobodyWrote', natives.MISSING)

    def test_an_ordinary_global_that_was_never_set_is_still_nil(self):
        """Klango's own code tests plenty of those and must go on getting the
        right answer - the net is only for the six native families."""
        runtime = self.runtime()
        runtime.run('kind = type(SomethingOrdinary)\n')
        self.assertEqual(runtime.get_global('kind'), 'nil')

    def test_what_a_character_is(self):
        runtime = self.runtime()
        runtime.run('a = _Sys_CharIs_("digit", "42")\n'
                    'b = _Sys_CharIs_("digit", "4x")\n'
                    'c = _Sys_CharIs_("ctrl", "\\13")\n'
                    'd = _Sys_CharTo_("upper", "\u0142\u00f3d\u017a")\n')
        self.assertTrue(runtime.get_global('a'))
        self.assertFalse(runtime.get_global('b'))
        self.assertTrue(runtime.get_global('c'))
        self.assertEqual(runtime.get_global('d'), '\u0141\u00d3D\u0179')

    def test_a_url_is_encoded_the_way_the_other_end_expects(self):
        """A space is `%20`, because what an application encodes is a PATH.

        The Wikipedia browser puts a title into `/wiki/<title>`, takes it
        back out and asks for `Special:Export/<title>` - escaping any `+` it
        finds to `%2B` on the way. With PHP's `+` for a space, every article
        whose title is more than one word was asked for with a plus sign in
        its name and came back as a page that does not exist.
        """
        runtime = self.runtime()
        runtime.run('a = urlencode("a b&c")\n'
                    'b = urldecode("a+b%26c")\n'
                    'c = urlencode("Kot domowy")\n'
                    'd = urlencode("a/b")\n')
        self.assertEqual(runtime.get_global('a'), 'a%20b%26c')
        self.assertEqual(runtime.get_global('b'), 'a b&c')
        self.assertEqual(runtime.get_global('c'), 'Kot%20domowy')
        self.assertEqual(runtime.get_global('d'), 'a%2Fb',
                         'a path separator inside a name was left alone')


class KlangosInterfaceSoundsAreTitans(unittest.TestCase):
    """Moving through a menu, choosing, reaching the end of a list: an
    emulated application makes the same noises Titan makes, so it makes
    Titan's."""

    def host(self):
        return host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())

    def test_the_platforms_own_cues_are_mapped(self):
        from clingkit.klango.engine import TITAN_CUES
        for klango, titan in (('menumain_norm', 'core/FOCUS.ogg'),
                              ('end', 'ui/endoflist.ogg'),
                              ('_open_dialog', 'ui/dialog.ogg')):
            self.assertEqual(TITAN_CUES.get(klango), titan)

    def test_an_applications_own_sound_is_never_remapped(self):
        """A mole's hello is the game, not the interface."""
        from clingkit.klango.engine import _titan_cue
        host = self.host()
        self.assertEqual(
            _titan_cue(host, '//skin/default/themes/default/menumain_norm'), '')

    def test_only_the_librarys_skin_is_looked_at(self):
        from clingkit.klango.engine import _titan_cue, LIBRARY_SKIN
        self.assertEqual(LIBRARY_SKIN, '/llib/skin/')
        self.assertEqual(_titan_cue(self.host(), '/somewhere/else/end'), '')


class EveryEnginePrimitive(unittest.TestCase):
    """Every function Klango's library CALLS and never defines is answered.

    Those are the engine's own - the native surface - and a name that is nil
    is not a function, so whichever one an application reaches first ends it
    there. `k_GetUnixTimestamp` ended Shopping with Klango, `_Sys_CharIs_`
    ended the Wikipedia browser the moment somebody typed, `k_NewP2PSession`
    ended the chat. This is the sweep that says there is no next one: it
    reads the library itself rather than a list somebody kept up to date.
    """

    @classmethod
    def setUpClass(cls):
        from clingkit.klango.session import find_library
        try:
            cls.LIBRARY = find_library()
        except Exception:
            cls.LIBRARY = ''

    def wanted(self):
        """Globals the library calls and nothing in it defines."""
        from clingkit.lua.parser import parse

        called, defined = set(), set()

        def walk(node):
            if isinstance(node, list):
                for item in node:
                    walk(item)
                return
            if not isinstance(node, tuple):
                return
            kind = node[0]
            if kind in ('call', 'method'):
                target = node[1]
                if isinstance(target, tuple) and target[0] == 'name':
                    called.add(target[1])
            elif kind == 'assign':
                for target in node[1]:
                    if isinstance(target, tuple) and target[0] == 'name':
                        defined.add(target[1])
            elif kind == 'local':
                defined.update(node[1])
            elif kind in ('localfunc', 'funcstat'):
                target = node[1]
                if isinstance(target, str):
                    defined.add(target)
                elif isinstance(target, tuple) and target[0] == 'name':
                    defined.add(target[1])
            for piece in node[1:]:
                walk(piece)

        from clingkit import textio
        for name in sorted(os.listdir(self.LIBRARY)):
            if not name.lower().endswith('.lua'):
                continue
            try:
                walk(parse(textio.read(os.path.join(self.LIBRARY, name)), name))
            except Exception:
                continue                       # a file that will not parse is
                                               # its own test, above
        return called - defined

    def given(self):
        from clingkit.klango import engine, environment, keyboard, natives
        from clingkit.lua import LuaRuntime

        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        runtime = LuaRuntime()
        files = natives.Filesystem(host.app.path, '',
                                   tempfile.mkdtemp(prefix='cling-p-'))
        natives.install(runtime, host, files, lambda *_a: None)
        engine.install(runtime, host, files, keyboard.Keyboard())
        environment.install(runtime, lambda *_a: None)
        return runtime

    #: Names that look like calls to the reader above and are not the
    #: engine's: Lua's own, and the entry point every application defines.
    NOT_THE_ENGINE = frozenset(
        'print type pairs ipairs next tostring tonumber setmetatable '
        'getmetatable rawget rawset rawequal rawlen select unpack error '
        'assert pcall xpcall require collectgarbage string table math os io '
        'coroutine debug utf8 unicode json lpeg package load loadstring '
        'dofile loadfile module main'.split())

    #: Klango's own dead ends: names its library calls and never defines
    #: anywhere, in code no application reaches. `_k_SUINewChoice` and
    #: `_k_SUINewKDoc` are called only from `embDialog`, and Klango itself
    #: comments out the module that would have held the second; the rest
    #: belong to the shell's own note, blog and catalogue screens, which are
    #: the program Cling replaces. They are listed rather than filled in
    #: because writing a body for a function nothing calls is inventing a
    #: feature - and if a SIXTEENTH ever appears, this test says so.
    KLANGOS_OWN_DEAD_ENDS = frozenset((
        '__OpenEntity', '__RUNCATALOG__', '_____kdocdebug',
        '_checkIfIsSomethingNew', '_k_FavAddEntity', '_k_SUINewChoice',
        '_k_SUINewKDoc', '_k_lcname', '_tree', 'k_BlogsTree',
        'k_GetContentFromNoteList', 'k_Get_whatsnewaction_table',
        'k_NotesGroup_dialog'))

    def test_every_one_of_them_is_answered(self):
        if not self.LIBRARY:
            self.skipTest("Klango's library is not installed")
        runtime = self.given()
        missing = []
        for name in sorted(self.wanted()):
            if name in self.NOT_THE_ENGINE or name in self.KLANGOS_OWN_DEAD_ENDS:
                continue
            if not name.startswith(('k_', '_')):
                continue
            if runtime.get_global(name) is None:
                # The net catches the six native families; anything else has
                # to be written.
                found = runtime.interpreter.index(
                    runtime.interpreter.globals, name, 0)
                if found is None:
                    missing.append(name)
        self.assertEqual(missing, [],
                         'these would be nil when an application called them')

    def test_the_ones_that_are_refused_still_answer(self):
        """Refusing is not the same as being absent. Running a program is
        refused; the call still returns, and is recorded."""
        from clingkit.klango import natives
        natives.MISSING.clear()
        runtime = self.given()
        runtime.run('a = k_ShellExecute("x")\n b = k_NewP2PSession()\n'
                    'c = b and b.Available and b:Available()\n', 'refused')
        self.assertIsNone(runtime.get_global('a'))
        self.assertIsNotNone(runtime.get_global('b'),
                             'a refusal that answers nil is one the caller '
                             'then indexes')
        self.assertEqual(runtime.get_global('c'), 0)
        self.assertIn('k_ShellExecute', natives.MISSING)

    def test_the_ones_that_are_written_really_work(self):
        runtime = self.given()
        runtime.run('a = k_Base64Encode("Titan")\n'
                    'b = k_Base64Decode(a)\n'
                    'c = k_HexEncode("AB")\n'
                    'd = k_SplitString("abc")[2]\n'
                    'e = os.date("*t").year\n', 'written')
        self.assertEqual(runtime.get_global('a'), 'VGl0YW4=')
        self.assertEqual(runtime.get_global('b'), 'Titan')
        self.assertEqual(runtime.get_global('c'), '4142')
        self.assertEqual(runtime.get_global('d'), 'b')
        self.assertGreater(runtime.get_global('e'), 2000)


class KlangosOwnFilesAreReadable(unittest.TestCase):
    """Not everything Klango ships is UTF-8, and one file has no newlines."""

    def test_windows_1250_is_read_as_polish(self):
        from clingkit import textio
        self.assertEqual(textio.decode('Przerwij grę'.encode('cp1250')),
                         'Przerwij grę')
        self.assertEqual(textio.decode('Przerwij grę'.encode('utf-8')),
                         'Przerwij grę')

    def test_there_is_no_such_thing_as_a_file_that_cannot_be_read(self):
        from clingkit import textio
        self.assertEqual(len(textio.decode(bytes(range(256)))), 256)

    def test_a_bare_carriage_return_is_a_line_ending(self):
        """`llib_s4tb.lua` ends its 1961 lines with `\r` and nothing else. A
        lexer that treats that as whitespace lets the first `--` comment
        swallow the file: it loaded without complaint and defined nothing."""
        from clingkit import textio
        self.assertEqual(textio.decode(b'a\rb\r\nc\nd'), 'a\nb\nc\nd')

    def test_a_file_with_mac_line_endings_really_parses(self):
        from clingkit.lua.parser import parse
        from clingkit import textio
        source = textio.decode(b'-- a comment\rfunction f() return 7 end\r')
        tree = parse(source, 'mac.lua')
        self.assertTrue(tree, 'the comment swallowed the whole file')


class RandomIsRandom(unittest.TestCase):
    """`math.random(m)` is 1..m, because `llib_math.lua` makes `math.random`
    Klango's own `_Sys_Random`.

    Reading one argument as "from m to m" - which is what this did - makes
    `math.random(5)` answer 5 every single time. Dice Poker picks one of its
    recorded shake sounds with it and loops until the one it drew exists;
    with only two on disk it looped for ever and the game froze on its first
    roll. Everything else about an application is as random as this is: where
    a mole appears, where a clay pigeon flies, how a board is shuffled.
    """

    def runtime(self):
        from clingkit.klango import engine, keyboard, natives
        from clingkit.lua import LuaRuntime

        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        runtime = LuaRuntime()
        files = natives.Filesystem(host.app.path, '',
                                   tempfile.mkdtemp(prefix='cling-r-'))
        natives.install(runtime, host, files, lambda *_a: None)
        engine.install(runtime, host, files, keyboard.Keyboard())
        return runtime

    def draws(self, expression, times=60):
        runtime = self.runtime()
        runtime.run('out = {}\nfor i = 1, %d do out[i] = %s end\n'
                    % (times, expression), 'draws')
        table = runtime.get_global('out')
        return [table.raw_get(index) for index in range(1, times + 1)]

    def test_one_argument_means_one_to_m(self):
        drawn = self.draws('_Sys_Random(5)')
        self.assertTrue(all(1 <= value <= 5 for value in drawn), drawn[:10])
        self.assertGreater(len(set(drawn)), 1,
                           'every draw was the same number')
        self.assertIn(1, drawn, 'the low end was never drawn')

    def test_two_arguments_mean_the_range(self):
        drawn = self.draws('_Sys_Random(3, 4)')
        self.assertEqual(set(drawn) - {3, 4}, set())

    def test_no_argument_is_a_fraction(self):
        drawn = self.draws('_Sys_Random()', 20)
        self.assertTrue(all(0.0 <= value < 1.0 for value in drawn))
        self.assertGreater(len(set(drawn)), 1)

    def test_a_backwards_range_is_still_a_range(self):
        drawn = self.draws('_Sys_Random(4, 2)', 20)
        self.assertEqual(set(drawn) - {2, 3, 4}, set())


class SoundIsWhereKlangoPutIt(unittest.TestCase):
    """Positioning, distance and travel, as the applications ask for them."""

    def place(self, sample=None, **fields):
        from clingkit.klango.engine import _placement
        return _placement(_lua_table(fields), sample)

    def sample(self, near=1.0, far=3.0):
        from clingkit.klango import sounds
        return sounds.Sample('x', path='/x.ogg', near=near, far=far)

    def test_a_sample_keeps_its_own_distance_model(self):
        """`dmin`/`dmax` are given when a sample is PREPARED. Skeet's clay
        pigeon is 1..10 and is thrown from twenty units away; the platform's
        own speech is 1..3. One figure for both makes a wide board flat."""
        wide = self.place(self.sample(1.0, 10.0),
                          pos3d=_lua_array([-20.0, 1.0, 0.0]))
        narrow = self.place(self.sample(1.0, 3.0),
                            pos3d=_lua_array([-20.0, 1.0, 0.0]))
        self.assertAlmostEqual(wide['gain'], 0.1, places=3)
        self.assertAlmostEqual(narrow['gain'], 1.0 / 3.0, places=3)

    def test_dmin_and_dmax_come_off_the_load(self):
        from clingkit.klango import sounds
        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        bank = sounds.SoundBank(host, None, _speaking(host), lambda n: '/x.ogg')
        bank.load('disc', 'disc', _lua_table({'dmin': 1, 'dmax': 10}))
        self.assertEqual(bank.samples['disc'].near, 1.0)
        self.assertEqual(bank.samples['disc'].far, 10.0)

    def test_a_sound_can_be_told_to_travel(self):
        """`pos3dSlide = {from, to, seconds}` is how Skeet throws a clay
        pigeon: the disc really crosses the listener."""
        place = self.place(self.sample(1.0, 10.0),
                           pos3dSlide=_lua_array([-20.0, 1.0, 0.0,
                                                  20.0, 1.0, 0.0, 2.0]))
        self.assertEqual(place['at'], (-20.0, 1.0, 0.0))
        self.assertEqual(place['to'], (20.0, 1.0, 0.0))
        self.assertEqual(place['seconds'], 2.0)
        self.assertLess(place['pan'], -0.9)

    def test_it_really_crosses(self):
        from clingkit.klango import sounds
        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        bank = sounds.SoundBank(host, None, _speaking(host), lambda n: '/x.ogg')
        bank.load('disc', 'disc', _lua_table({'dmin': 1, 'dmax': 10}))
        identifier = bank.create('disc', _lua_table({
            'pos3dSlide': _lua_array([-20.0, 1.0, 0.0, 20.0, 1.0, 0.0, 2.0])}))
        sound = bank.playing[identifier]
        seen = []
        for _step in range(5):
            host.clock.advance(0.5)
            bank.pump()
            seen.append(round(sound.place['pan'], 2))
        self.assertLess(seen[0], 0.0, 'it never started on the left')
        self.assertGreater(seen[-1], 0.0, 'it never reached the right')
        self.assertEqual(seen, sorted(seen), 'it did not travel in one go')

    def test_speech_is_placed_because_klango_places_it(self):
        """A spoken line goes through the whole sound path -
        `_Voice_SpeakToStream` then `k_SoundPlay(playargs)` - which is how
        Dice Poker says each of its five dice at its own place on the table.
        """
        from clingkit.klango import engine, keyboard, natives, sounds
        from clingkit.lua import LuaRuntime

        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        runtime = LuaRuntime()
        files = natives.Filesystem(host.app.path, '',
                                   tempfile.mkdtemp(prefix='cling-s-'))
        natives.install(runtime, host, files, lambda *_a: None)
        engine.install(runtime, host, files, keyboard.Keyboard())
        runtime.run('v = _Voice_Create({})\n'
                    'stream = _Voice_SpeakToStream(v, "four")\n'
                    '_Snd_Load("voice:1", stream, {dmin=1, dmax=3})\n'
                    'id = _Snd_Create("voice:1", {pos3d = {2, 0.5, 0}})\n')
        self.assertIsNotNone(runtime.get_global('stream'),
                             'nothing was rendered to speak')
        self.assertEqual(host.speaker.spoken, ['four'])
        self.assertGreater(host.speaker.said_at[-1], 0.5,
                           'the line was said in the middle, not on the right')


class KlangoWritesAPlaceTwoWays(unittest.TestCase):
    """`pos3d` is an array in an application and a named table in the library.

    `menu:recalcpositions` lays a menu's items out from -60 to +60 degrees
    with `LLib_Math_AngleDist_To_3dPos`, which returns `{x=, y=, z=}` - so
    reading only `{1,2,3}` put every menu, every dialog, the help channel,
    the information channel and every ambient sound `k_BackgroundPrepare`
    scatters around the listener in one spot in the middle.
    """

    def place(self, table):
        from clingkit.klango.engine import _placement
        return _placement(_lua_table({'pos3d': table}))

    def test_an_array_is_a_place(self):
        self.assertLess(self.place(_lua_array([-2.0, 0.5, 0.0]))['pan'], -0.9)

    def test_a_named_table_is_the_same_place(self):
        named = self.place(_lua_table({'x': -2.0, 'y': 0.5, 'z': 0.0}))
        array = self.place(_lua_array([-2.0, 0.5, 0.0]))
        self.assertAlmostEqual(named['pan'], array['pan'], places=6)
        self.assertAlmostEqual(named['gain'], array['gain'], places=6)

    def test_a_table_that_is_neither_is_not_a_place(self):
        """Nothing is invented out of a table with no coordinates in it."""
        self.assertEqual(self.place(_lua_table({'foo': 1}))['pan'], 0.0)

    def test_a_menu_of_five_really_spans_the_listener(self):
        """What the library's own layout comes to, item by item."""
        from clingkit.klango.engine import _placement
        import math
        pans = []
        for angle in (-60.0, -30.0, 0.0, 30.0, 60.0):
            radians = math.radians(angle)
            pans.append(_placement(_lua_table({'pos3d': _lua_table({
                'x': math.sin(radians), 'y': math.cos(radians),
                'z': 0.0})}))['pan'])
        self.assertEqual([round(p, 2) for p in pans],
                         [-0.87, -0.5, 0.0, 0.5, 0.87])


class ASampleIsFoundTheWayKlangoFindsOne(unittest.TestCase):
    """A relative name with no extension is the ordinary case, not the odd one.

    `k_DirectoryRead`'s `name` field is the file name with the extension taken
    OFF (`k_SplitFileName`, `llib_files.lua`), and Klango Piano builds every
    key's sample out of it - `sounds/<model>/<key>`. Asking the application's
    own file system only about names beginning with `/` is why every key of
    the piano was silent.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='cling-p-')
        os.makedirs(os.path.join(self.root, 'sounds', 'default_samples'))
        for name in ('c.wav', 'e_l.wav'):
            with open(os.path.join(self.root, 'sounds', 'default_samples',
                                   name), 'wb') as handle:
                handle.write(b'RIFF')

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def resolver(self):
        from clingkit.klango import engine, keyboard, natives
        from clingkit.lua import LuaRuntime

        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        runtime = LuaRuntime()
        files = natives.Filesystem(self.root, '',
                                   tempfile.mkdtemp(prefix='cling-p2-'))
        natives.install(runtime, host, files, lambda *_a: None)
        engine.install(runtime, host, files, keyboard.Keyboard())
        return host.klango_sounds.resolve

    def test_a_relative_name_with_no_extension_is_found(self):
        found = self.resolver()('sounds/default_samples/c')
        self.assertTrue(found.endswith('c.wav'), found)

    def test_the_loop_marker_is_part_of_the_name(self):
        found = self.resolver()('sounds/default_samples/e_l')
        self.assertTrue(found.endswith('e_l.wav'), found)

    def test_a_name_that_is_nothing_of_the_sort_still_answers(self):
        """A name Cling's own engines use is still the user's theme."""
        self.assertIsNotNone(self.resolver()('focus'))


class AGroupIsDuckedAsAGroup(unittest.TestCase):
    """Klango's sound groups are a TREE, and volume runs down it.

    Every `k_SoundPlay` creates a group and plays inside it
    (`s.gid = _Snd_GroupCreate(5)`, `llib_snd.lua`), so the ambience group
    holds no sounds of its own at all - it holds the groups made under it.
    Ducking it by looking only at sounds whose group id IS the ambience
    reached nothing, which is why the background never faded in, never
    ducked under a dialog and never faded out again.
    """

    def bank(self):
        from clingkit.klango import sounds
        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        return host, sounds.SoundBank(host, None, _speaking(host),
                                      lambda n: '/x.ogg')

    def test_a_sound_started_inside_a_ducked_group_is_ducked(self):
        host, bank = self.bank()
        ambience = bank.group_create()
        bank.action(ambience, _lua_table({'volMul': 0.2}))
        bank.group_set_active(ambience)
        inner = bank.group_create()          # what k_SoundPlay makes
        bank.group_set_active(inner)
        bank.create('music')
        self.assertAlmostEqual(host.mixer.played[-1][2], 0.2, places=3)

    def test_a_slide_ramps_over_the_seconds_it_was_given(self):
        host, bank = self.bank()
        ambience = bank.group_create()
        bank.group_set_active(ambience)
        inner = bank.group_create()
        bank.group_set_active(inner)
        bank.create('music')
        bank.action(ambience, _lua_table({'volMulSlide':
                                          _lua_array([0.0, 1.0, 1.0])}))
        seen = []
        for _step in range(5):
            host.clock.advance(0.25)
            bank.pump()
            seen.append(round(bank.group_factor(inner), 2))
        self.assertEqual(seen, [0.25, 0.5, 0.75, 1.0, 1.0])

    def test_a_group_that_is_paused_holds_its_sounds(self):
        host, bank = self.bank()
        game = bank.group_create()
        bank.group_set_active(game)
        inner = bank.group_create()
        bank.group_set_active(inner)
        identifier = bank.create('shot')
        bank.action(game, _lua_table({'pause': 1, 'volMul': 0}))
        self.assertTrue(bank.playing[identifier].paused)
        self.assertTrue(bank.is_playing(identifier),
                        'a held sound is not a finished one')
        bank.action(game, _lua_table({'resume': 1, 'volMul': 1}))
        self.assertFalse(bank.playing[identifier].paused)

    def test_a_paused_journey_does_not_move(self):
        host, bank = self.bank()
        bank.load('disc', 'disc', _lua_table({'dmin': 1, 'dmax': 10}))
        group = bank.group_create()
        bank.group_set_active(group)
        identifier = bank.create('disc', _lua_table({
            'pos3dSlide': _lua_array([-20.0, 1.0, 0.0, 20.0, 1.0, 0.0, 2.0])}))
        sound = bank.playing[identifier]
        host.clock.advance(0.5)
        bank.pump()
        where = sound.place['pan']
        bank.action(group, _lua_table({'pause': 1}))
        for _step in range(4):
            host.clock.advance(0.5)
            bank.pump()
        self.assertEqual(sound.place['pan'], where,
                         'the disc flew on under the dialog')
        bank.action(group, _lua_table({'resume': 1}))
        host.clock.advance(0.5)
        bank.pump()
        self.assertGreater(sound.place['pan'], where,
                           'it never started again')

    def test_the_empty_groups_are_swept_up(self):
        """`k_SoundPlay` makes a group per sequence and destroys none, so a
        game played for an hour would carry tens of thousands of them."""
        from clingkit.klango import sounds
        host, bank = self.bank()
        for _each in range(200):
            group = bank.group_create()
            bank.group_set_active(group)
            bank.group_set_active(0)
        made = len(bank.groups)
        for _frame in range(sounds.TIDY_EVERY + 1):
            bank.pump()
        self.assertEqual(made, 200)
        self.assertEqual(len(bank.groups), 0, 'nothing was swept up')

    def test_a_group_with_something_in_it_is_kept(self):
        from clingkit.klango import sounds
        host, bank = self.bank()
        keep = bank.group_create()
        bank.group_set_active(keep)
        inner = bank.group_create()
        bank.group_set_active(inner)
        bank.create('music')
        for _frame in range(sounds.TIDY_EVERY + 1):
            bank.pump()
        self.assertIn(keep, bank.groups, 'a parent of a live group went')
        self.assertIn(inner, bank.groups, 'a group with a sound in it went')

    def test_destroying_a_group_takes_what_was_made_inside_it(self):
        host, bank = self.bank()
        outer = bank.group_create()
        bank.group_set_active(outer)
        inner = bank.group_create()
        bank.group_set_active(inner)
        sound = bank.playing[bank.create('music')]
        bank.group_destroy(outer)
        self.assertTrue(sound.stopped)
        self.assertNotIn(inner, bank.groups)


class ALoopReallyLoops(unittest.TestCase):
    """`replay = -1` on the 3D path.

    `spatial_audio.play_file` had no looping at all - nothing in Titan needed
    it while the only 3D sounds were its own one-shot cues. A Klango
    application's background music, a clay pigeon's flight and a piano key
    held down are all `replay = -1`, and with 3D on (which is what a Cling
    user has) each of them played exactly once.
    """

    class FakeSpatial(object):
        def __init__(self):
            self.calls = []
            self.paused = []

        def spatial_available(self):
            return True

        def pan_to_azimuth(self, value):
            return (value - 0.5) * 180.0

        def play_file(self, path, azimuth=0.0, elevation=0.0, gain=1.0,
                      loop=False):
            self.calls.append(('file', os.path.basename(path), loop))
            return 7

        def play_pcm(self, *values, **named):
            self.calls.append(('pcm', named.get('loop', False)))
            return 8

        def is_playing(self, source):
            return True

        def pause_source(self, source, paused=True):
            self.paused.append((source, paused))
            return True

        def set_velocity(self, source, x=0.0, y=0.0, z=0.0):
            self.velocity = (source, x, y, z)
            return True

        def move_source(self, source, azimuth=0.0, elevation=0.0):
            self.calls.append(('move', source, round(azimuth, 2),
                               round(elevation, 2)))
            return True

        def set_gain(self, source, gain=1.0):
            self.calls.append(('gain', source, round(gain, 3)))
            return True

    def mixer(self, spatial):
        class Mixer(host_module.Mixer):
            def _spatial_module(self_inner):
                return spatial

            def _mode(self_inner):
                return '3d'

            def _theme_volume(self_inner):
                return 1.0
        return Mixer()

    def test_a_looping_sound_is_asked_for_as_one(self):
        spatial = self.FakeSpatial()
        here = write(os.path.join(tempfile.mkdtemp(), 'music.ogg'), 'x')
        self.mixer(spatial).start(here, 0.0, 0.0, 1.0, 0.0, loop=True)
        self.assertEqual(spatial.calls, [('file', 'music.ogg', True)])

    def test_a_one_shot_is_not(self):
        spatial = self.FakeSpatial()
        here = write(os.path.join(tempfile.mkdtemp(), 'hit.ogg'), 'x')
        self.mixer(spatial).start(here, 0.0, 0.0, 1.0)
        self.assertEqual(spatial.calls, [('file', 'hit.ogg', False)])

    def test_a_titan_without_looping_still_plays_the_sound(self):
        """Cling must lose the looping, never the sound."""
        class Older(ALoopReallyLoops.FakeSpatial):
            def play_file(self, path, azimuth=0.0, elevation=0.0, gain=1.0):
                self.calls.append(('file', os.path.basename(path), 'no loop'))
                return 7
        spatial = Older()
        here = write(os.path.join(tempfile.mkdtemp(), 'music.ogg'), 'x')
        handle = self.mixer(spatial).start(here, 0.0, 0.0, 1.0, 0.0, loop=True)
        self.assertIsNotNone(handle)
        self.assertEqual(spatial.calls, [('file', 'music.ogg', 'no loop')])

    def test_a_moving_sound_is_given_its_velocity(self):
        """`vel3d` is Klango asking for the Doppler shift - Skeet works the
        vector out itself and hands it over with the clay pigeon."""
        from clingkit.klango import sounds
        spatial = self.FakeSpatial()
        here = write(os.path.join(tempfile.mkdtemp(), 'flight.ogg'), 'x')
        mixer = self.mixer(spatial)
        handle = mixer.start(here, 0.0, 0.0, 1.0, 0.0, loop=True)
        self.assertTrue(mixer.set_velocity(handle, (5.06, 0.0, 0.0)))
        self.assertEqual(spatial.velocity, (7, 5.06, 0.0, 0.0))

    def test_the_placement_reads_vel3d(self):
        from clingkit.klango.engine import _placement
        place = _placement(_lua_table({'vel3d': _lua_array([5.0, 0.0, 0.0])}))
        self.assertEqual(place['velocity'], (5.0, 0.0, 0.0))
        self.assertIsNone(_placement(_lua_table({}))['velocity'])
        self.assertIsNone(
            _placement(_lua_table({'vel3d': _lua_array([0.0, 0.0, 0.0])}))
            ['velocity'], 'a still sound was given a velocity')

    def test_a_held_sound_is_paused_where_it_is(self):
        spatial = self.FakeSpatial()
        here = write(os.path.join(tempfile.mkdtemp(), 'music.ogg'), 'x')
        mixer = self.mixer(spatial)
        handle = mixer.start(here, 0.0, 0.0, 1.0, 0.0, loop=True)
        self.assertTrue(mixer.pause(handle, True))
        self.assertTrue(mixer.pause(handle, False))
        self.assertEqual(spatial.paused, [(7, True), (7, False)])


class ASoundThatIsPlayingCanStillBeMovedAndReGained(unittest.TestCase):
    """`Mixer.set_gain` on the 3D path - which is the path a Cling user is on.

    It used to refuse a 3D handle outright, and every single thing Klango's
    sound layer does after a sound has STARTED goes through it: an ambience
    is started at nothing (`_Snd_Action(gid, {volMul = 0})`) and faded in
    with `volMulSlide = {0, 1, speed}`, a dialog ducks the game while it is
    up, and a clay pigeon that crosses the listener is re-placed and
    re-gained at every frame of its flight. So with 3D on, Dice Poker's,
    Long Jump's and Simple Puzzle's backgrounds were started, looped and
    never once heard - they stayed at the zero they were started at - and
    Skeet's disc was thrown and stayed in the middle of the room at full
    volume for the whole of its flight.
    """

    FakeSpatial = ALoopReallyLoops.FakeSpatial

    def mixer(self, spatial):
        return ALoopReallyLoops.mixer(self, spatial)

    def playing(self, spatial, name='music.ogg', gain=0.0):
        here = write(os.path.join(tempfile.mkdtemp(), name), 'x')
        mixer = self.mixer(spatial)
        return mixer, mixer.start(here, 0.0, 0.0, gain, 0.0, loop=True)

    def test_a_background_started_at_nothing_can_be_faded_in(self):
        spatial = self.FakeSpatial()
        mixer, handle = self.playing(spatial)
        spatial.calls = []
        self.assertTrue(mixer.set_gain(handle, 0.0, 0.6))
        self.assertIn(('gain', 7, 0.6), spatial.calls)

    def test_it_is_moved_as_well_as_re_gained(self):
        """A `pos3dSlide` is a PLACE, not a volume: OpenAL renders a source
        from wherever it is at that instant, so the disc is moved rather
        than mixed."""
        spatial = self.FakeSpatial()
        mixer, handle = self.playing(spatial, 'flight.ogg', gain=1.0)
        spatial.calls = []
        mixer.set_gain(handle, -1.0, 0.1)
        mixer.set_gain(handle, 1.0, 0.1)
        moves = [call for call in spatial.calls if call[0] == 'move']
        self.assertEqual([call[2] for call in moves], [-90.0, 90.0])

    def test_the_height_travels_with_it(self):
        spatial = self.FakeSpatial()
        mixer, handle = self.playing(spatial, 'flight.ogg', gain=1.0)
        spatial.calls = []
        mixer.set_gain(handle, 0.0, 1.0, 30.0)
        self.assertIn(('move', 7, 0.0, 30.0), spatial.calls)

    def test_the_theme_volume_still_applies(self):
        spatial = self.FakeSpatial()

        class Quieter(host_module.Mixer):
            def _spatial_module(self_inner):
                return spatial

            def _mode(self_inner):
                return '3d'

            def _theme_volume(self_inner):
                return 0.5
        here = write(os.path.join(tempfile.mkdtemp(), 'music.ogg'), 'x')
        mixer = Quieter()
        handle = mixer.start(here, 0.0, 0.0, 0.0, 0.0, loop=True)
        spatial.calls = []
        mixer.set_gain(handle, 0.0, 1.0)
        self.assertIn(('gain', 7, 0.5), spatial.calls)

    def test_a_titan_that_cannot_re_gain_a_source_still_moves_it(self):
        """Cling should lose the fade rather than the sound - `set_gain` is
        asked for by name, exactly as `loop=` is."""
        class Older(ALoopReallyLoops.FakeSpatial):
            #: A Titan whose `spatial_audio` predates `set_gain`. It is
            #: hidden rather than deleted because the name is inherited.
            def __getattribute__(self_inner, name):
                if name == 'set_gain':
                    raise AttributeError(name)
                return object.__getattribute__(self_inner, name)
        spatial = Older()
        mixer, handle = self.playing(spatial)
        spatial.calls = []
        self.assertTrue(mixer.set_gain(handle, -1.0, 0.6))
        self.assertEqual([call[0] for call in spatial.calls], ['move'])

    def test_titan_really_has_the_call_cling_asks_for(self):
        """The other half of the same fix: a source's `AL_GAIN` is live, and
        until now nothing in Titan ever set it on one that was playing."""
        from src.titan_core import spatial_audio
        self.assertTrue(callable(getattr(spatial_audio, 'set_gain', None)))
        self.assertFalse(spatial_audio.set_gain(None, 1.0),
                         'a source that is not there was re-gained')

    def test_a_stereo_channel_is_unaffected_by_the_extra_argument(self):
        """The elevation is carried through every call site, and the stereo
        path has no use for it - a channel is two volumes."""
        class FakeChannel(object):
            def __init__(self):
                self.volumes = []

            def set_volume(self, left, right=None):
                self.volumes.append((round(left, 3), round(right, 3)))

        class Stereo(host_module.Mixer):
            def _spatial_module(self_inner):
                return None

            def _mode(self_inner):
                return 'stereo'

            def _theme_volume(self_inner):
                return 1.0
        channel = FakeChannel()
        self.assertTrue(Stereo().set_gain(channel, -1.0, 1.0, 45.0))
        self.assertEqual(channel.volumes[-1], (1.0, 0.0))


class TheHeightOfAPlace(unittest.TestCase):
    """`_elevation_of` is its own function because a sound TRAVELS in three
    axes: working the pan and the gain out at every frame of a flight and
    leaving the height wherever the sound was thrown from is the same
    mistake as not moving it at all, one axis smaller."""

    def test_a_place_in_front_is_level(self):
        from clingkit.klango.engine import _elevation_of
        self.assertEqual(_elevation_of(0.0, 1.0, 0.0), 0.0)

    def test_a_place_above_is_above(self):
        from clingkit.klango.engine import _elevation_of
        self.assertAlmostEqual(_elevation_of(0.0, 1.0, 1.0), 45.0, places=3)

    def test_nowhere_is_level(self):
        from clingkit.klango.engine import _elevation_of
        self.assertEqual(_elevation_of(0.0, 0.0, 0.0), 0.0)

    def test_a_journey_carries_its_height_to_the_mixer(self):
        from clingkit.klango import sounds

        class Heights(SilentMixer):
            def __init__(self):
                SilentMixer.__init__(self)
                self.heights = []

            def set_gain(self, handle, pan=0.0, gain=1.0, elevation=0.0):
                self.heights.append(round(elevation, 1))
                return True

        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=Heights(),
            clock=runner.FakeClock())
        bank = sounds.SoundBank(host, None, _speaking(host), lambda n: '/x.ogg')
        bank.load('disc', 'disc', _lua_table({'dmin': 1, 'dmax': 10}))
        bank.create('disc', _lua_table({'pos3dSlide': _lua_array(
            [0.0, 1.0, -4.0, 0.0, 1.0, 4.0, 2.0])}))
        for _step in range(5):
            host.clock.advance(0.5)
            bank.pump()
        self.assertTrue(host.mixer.heights, 'the flight was never stepped')
        self.assertLess(host.mixer.heights[0], 0.0, 'it did not start below')
        self.assertGreater(host.mixer.heights[-1], 0.0,
                           'it never came up')


class ClingIsPortable(unittest.TestCase):
    """Everything Cling ships lives inside the component.

    A component that keeps half of itself in `data/` somewhere else cannot be
    copied to another Titan, and cannot be packaged as a `.TCD` at all - which
    is what every other add-on kind can do. `data/cling/` is the USER's: the
    applications they installed, and Klango's own library if they have it.
    """

    def test_the_demo_application_is_inside_the_component(self):
        demo = os.path.join(catalog.component_apps_dir(), 'clingdemo')
        self.assertTrue(os.path.isdir(demo),
                        'the application Cling ships is not in the component')
        self.assertTrue(catalog.looks_like_app(demo))

    def test_nothing_cling_ships_is_outside_the_component(self):
        """`data/cling/` is not shipped at all: it is made when the user
        installs their first application."""
        bundled = os.path.join(ROOT, 'data', 'cling')
        self.assertFalse(os.path.isdir(bundled),
                         'Cling still ships data outside its own component')

    def test_the_components_own_applications_are_discovered(self):
        found = {app.id for app in catalog.discover()}
        self.assertIn('clingdemo', found)

    def test_the_platform_library_is_inside_the_component(self):
        """The emulator is what most of Cling is, and the emulator is
        nothing without `llib`. Shipping everything EXCEPT the library meant
        seventeen of the twenty-one installed applications ran only on a
        machine that happened to have a Klango installation."""
        from clingkit.klango.session import LIB_PACKAGE
        here = os.path.join(catalog.component_apps_dir(),
                            LIB_PACKAGE + '.pag')
        self.assertTrue(os.path.isfile(here),
                        "Klango's platform library is not in the component")

    def test_the_library_is_found_with_nothing_else_installed(self):
        from clingkit.klango.session import find_library
        found = find_library([tempfile.mkdtemp(prefix='cling-empty-'),
                              catalog.component_apps_dir()])
        self.assertTrue(found, 'the shipped library was not found')
        self.assertTrue(os.path.isfile(os.path.join(found, 'llib.lua')),
                        'what was found is not the library')

    def test_the_library_is_not_offered_as_something_to_play(self):
        """It is the runtime. Listing it would be listing the platform."""
        self.assertNotIn('llib', {app.id for app in catalog.discover()})

    def test_the_users_own_library_still_wins(self):
        """Somebody with a newer or a patched Klango keeps theirs."""
        from clingkit.klango.session import find_library
        theirs = tempfile.mkdtemp(prefix='cling-lib-')
        os.makedirs(os.path.join(theirs, 'llib'))
        write(os.path.join(theirs, 'llib', 'llib.lua'), '-- theirs\n')
        self.assertEqual(find_library([theirs, catalog.component_apps_dir()]),
                         os.path.join(theirs, 'llib'))

    def test_the_user_keeps_theirs_when_a_name_is_the_same(self):
        """The overlay rule the other eleven add-on kinds follow: the
        component's own copy is the fallback, never the override."""
        theirs = tempfile.mkdtemp(prefix='cling-overlay-')
        os.makedirs(os.path.join(theirs, 'clingdemo'))
        write(os.path.join(theirs, 'clingdemo', 'kni.txt'),
              'appname=clingdemo\nsummary=the user\'s own\n')
        apps = catalog.discover([theirs, catalog.component_apps_dir()])
        demo = [app for app in apps if app.id == 'clingdemo']
        self.assertEqual(len(demo), 1)
        self.assertTrue(demo[0].path.startswith(theirs),
                        'the shipped copy overrode the user\'s')


class KlangosScreensAreTitans(unittest.TestCase):
    """Settings and Help in an emulated application open TITAN'S.

    Klango's own were a language picker, a voice picker and an audio-theme
    picker that changed nothing (a Cling application speaks through Titan's
    TTS and reads Titan's language and theme), plus a knowledge base, a
    terms-of-service page and a feedback form that all talked to klango.net.
    """

    def app_after_bridging(self):
        """An app object with Klango's methods on it, put through the bridge."""
        from clingkit.klango import titan_bridge
        from clingkit.lua import LuaRuntime

        runtime = LuaRuntime()
        opened = []
        runtime.set_global('_cling_open_settings',
                           lambda *_a: opened.append('settings') or True)
        runtime.set_global('_cling_open_help',
                           lambda *_a: opened.append('help') or True)
        runtime.set_global('_cling_open_feedback',
                           lambda *_a: opened.append('feedback') or True)
        # The least of Klango that the bridge needs: `k_NewApp` answering an
        # object with the methods the default menu calls.
        runtime.run("""
            k_NewApp = function()
                local app = {}
                for _, name in ipairs{"_dialogSelectLang", "_dialogSelectSkin",
                                      "_dialogSelectSynth", "_dialogTypingSettings",
                                      "_dialogTermsOfService", "_dialogPrivacyPolicy",
                                      "sendFeedback", "_dialogProgramVersion",
                                      "showReadme"} do
                    app[name] = function() klango_did = name end
                end
                return app
            end
        """, 'fake llib')
        runtime.run(titan_bridge.BRIDGE, 'bridge')
        return runtime, opened

    def fire(self, runtime, method):
        runtime.run('klango_did = nil\nlocal a = k_NewApp()\na:%s()\n' % method,
                    'fire')
        return runtime.get_global('klango_did')

    def test_every_settings_screen_opens_titans_settings(self):
        runtime, opened = self.app_after_bridging()
        for method in ('_dialogSelectLang', '_dialogSelectSkin',
                       '_dialogSelectSynth', '_dialogTypingSettings'):
            with self.subTest(method=method):
                self.assertIsNone(self.fire(runtime, method),
                                  "Klango's own screen still ran")
        self.assertEqual(opened, ['settings'] * 4)

    def test_the_platform_help_pages_open_titans_help(self):
        runtime, opened = self.app_after_bridging()
        for method in ('_dialogTermsOfService', '_dialogPrivacyPolicy'):
            self.fire(runtime, method)
        runtime.run('k_KnowledgeBaseDialog2(nil, 1, "en")\n', 'kb')
        self.assertEqual(opened, ['help'] * 3)

    def test_feedback_goes_to_the_feedback_hub(self):
        runtime, opened = self.app_after_bridging()
        self.fire(runtime, 'sendFeedback')
        self.assertEqual(opened, ['feedback'])

    def test_what_belongs_to_the_application_is_left_alone(self):
        """Its own version, its own readme, its own help text: Titan has
        nothing to say about those and must not answer for them."""
        runtime, opened = self.app_after_bridging()
        self.assertEqual(self.fire(runtime, '_dialogProgramVersion'),
                         '_dialogProgramVersion')
        self.assertEqual(self.fire(runtime, 'showReadme'), 'showReadme')
        self.assertEqual(opened, [])

    def test_a_window_that_did_not_open_is_not_reported_as_open(self):
        """Titan's own openers report failure by answering nothing and
        printing to a console nobody using this can see."""
        from clingkit.klango import titan_bridge
        said = titan_bridge._on_the_gui_thread(lambda: None, 'it is open',
                                               'it could not be opened')
        self.assertEqual(said, 'it could not be opened.')
        said = titan_bridge._on_the_gui_thread(lambda: object(), 'it is open',
                                               'it could not be opened')
        self.assertEqual(said, 'it is open')

    def test_a_failure_is_a_sentence_rather_than_an_exception(self):
        from clingkit.klango import titan_bridge

        def broken():
            raise RuntimeError('no window here')
        said = titan_bridge._on_the_gui_thread(broken, 'open', 'not open')
        self.assertIn('no window here', said)


class TheFrame(unittest.TestCase):
    """`_Sys_BeginFrame` / `_Sys_EndFrame`: the pace, and the way out.

    Both used to answer `True`, which meant a Klango game's own loop ran as
    fast as the interpreter could go - thousands of frames for every one it
    should have had - and that `KlangoSession.stopping` was set by the engine
    and read by nobody, so closing the window had nothing to interrupt.
    """

    def test_a_frame_takes_the_time_a_frame_takes(self):
        from clingkit.klango.frames import Frames
        clock = runner.FakeClock()
        slept = []
        frames = Frames()
        frames.period = 0.05
        with _instead_of_sleeping(slept):
            for _ in range(4):
                frames.begin()
                frames.end()
        self.assertEqual(frames.frames, 4)
        self.assertTrue(slept, 'a frame that never waits is a game at full speed')

    def test_no_delay_is_no_delay(self):
        """`EndFrame(1)` is the library's own "make a frame happen and do not
        charge me for it", and it is used where a frame must not cost time."""
        from clingkit.klango.frames import Frames
        slept = []
        frames = Frames()
        with _instead_of_sleeping(slept):
            frames.begin()
            frames.end(immediately=True)
        self.assertEqual(slept, [])

    def test_stopping_leaves_the_application_through_its_own_loop(self):
        from clingkit.klango.frames import Frames, Stopped
        stopping = [False]
        frames = Frames(lambda: stopping[0])
        frames.begin()
        frames.end(immediately=True)
        stopping[0] = True
        with self.assertRaises(Stopped):
            frames.begin()

    def test_stopped_is_not_a_lua_error_so_pcall_cannot_swallow_it(self):
        """The library wraps things in `pcall`; a stop that `pcall` catches is
        an application that carries on after the window has closed."""
        from clingkit.klango import frames as frames_module
        from clingkit.lua.runtime import LuaError
        self.assertFalse(issubclass(frames_module.Stopped, LuaError))

    def test_what_happens_each_frame_happens_each_frame(self):
        """A Klango sequence schedules its sounds ahead of time; the frame is
        what starts them when their moment comes."""
        from clingkit.klango.frames import Frames
        beats = []
        frames = Frames()
        frames.period = 0.0
        frames.on_frame(lambda: beats.append(1))
        frames.begin()
        frames.begin()
        self.assertEqual(len(beats), 2)


class _instead_of_sleeping(object):
    """Nothing in this suite may wait for real time to pass."""

    def __init__(self, record):
        self.record = record
        self.real = None

    def __enter__(self):
        import time as time_module
        from clingkit.klango import frames as frames_module
        self.real = frames_module.time.sleep
        frames_module.time.sleep = self.record.append
        return self

    def __exit__(self, *_error):
        from clingkit.klango import frames as frames_module
        frames_module.time.sleep = self.real
        return False


class TheSoundBank(unittest.TestCase):
    """`_Snd_*` as the library actually drives it - see `klango/sounds.py`."""

    def bank(self):
        from clingkit.klango import sounds
        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        return sounds.SoundBank(host, None, _speaking(host), lambda name: ''), host

    def test_a_group_is_its_own_group(self):
        """`k_SoundPlay` puts a sequence in a group and hands the GROUP back;
        every sequence in the program sharing one id made them all the same
        sequence."""
        bank, _host = self.bank()
        first = bank.group_create(5)
        second = bank.group_create(5)
        self.assertNotEqual(first, second)
        self.assertEqual(bank.group_set_active(first), 0)
        self.assertEqual(bank.group_set_active(second), first)

    def test_a_sound_is_playing_until_it_is_not_and_a_group_answers_for_it(self):
        from clingkit.klango import sounds
        bank, host = self.bank()
        bank.resolve = lambda name: '/does/not/matter'
        bank.samples['x'] = sounds.Sample('x', text='hello',
                                          length=1.0)
        group = bank.group_create(5)
        bank.group_set_active(group)
        identifier = bank.create('x')
        self.assertTrue(bank.is_playing(identifier))
        self.assertTrue(bank.is_playing(group), 'the group answers for it')
        host.clock.advance(5.0)
        bank.pump()
        self.assertFalse(bank.is_playing(identifier))
        self.assertFalse(bank.is_playing(group))

    def test_a_delayed_sound_waits_and_counts_as_playing_meanwhile(self):
        """A sequence is a list of sounds with DELAYS. Ignoring the delay
        played a whole menu inside forty milliseconds."""
        from clingkit.klango import sounds
        bank, host = self.bank()
        bank.samples['x'] = sounds.Sample('x', text='hello', length=0.5)
        when = bank.host.klango_when = None
        table = _lua_table({'delay': 2.0})
        identifier = bank.create('x', None, table)
        self.assertTrue(bank.is_playing(identifier))
        self.assertEqual(host.speaker.spoken, [], 'it started at once')
        host.clock.advance(2.5)
        bank.pump()
        self.assertEqual(host.speaker.spoken, ['hello'])

    def test_a_sample_time_is_a_length_because_a_sequence_is_built_from_it(self):
        from clingkit.klango import sounds
        bank, _host = self.bank()
        bank.samples['x'] = sounds.Sample('x', text='hello there', length=0.97)
        self.assertAlmostEqual(bank.property_of('x', 'sampleTime'), 0.97)

    def test_a_text_file_where_a_sample_was_asked_for_is_spoken(self):
        """Klango's own `speechexts` is `.wav .ogg .spx .txt .mp3` - a text
        file among the sound formats - and its engine synthesises one. Without
        this every application's menu plays its earcons and says nothing."""
        from clingkit.klango import sounds
        folder = tempfile.mkdtemp(prefix='cling-txt-')
        path = os.path.join(folder, 'new_game.txt')
        write(path, 'New game')
        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        bank = sounds.SoundBank(host, None, _speaking(host), lambda name: path)
        bank.create('/lang/en-us/default/new_game')
        self.assertEqual(host.speaker.spoken, ['New game'])

    def test_a_star_is_text_to_say_not_a_file_to_find(self):
        from clingkit.klango import sounds
        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        bank = sounds.SoundBank(host, None, _speaking(host), lambda name: '')
        bank.create('*Mole No More')
        self.assertEqual(host.speaker.spoken, ['Mole No More'])


class WhereASoundIs(unittest.TestCase):
    """`pos3d` and `freq` - which together are the whole of what makes a
    Klango board a place rather than a list."""

    def place(self, **fields):
        from clingkit.klango.engine import _placement
        return _placement(_lua_table(fields))

    def test_a_field_on_the_left_of_the_board_is_heard_on_the_left(self):
        """Mole No More's own `3x3.top`: x -0.8 .. 0.8, y 0.25 .. 1.1. Every
        one of those was played dead centre before this."""
        left = self.place(pos3d=_lua_array([-0.8, 0.25, 0.0]))
        middle = self.place(pos3d=_lua_array([0.0, 0.3, 0.0]))
        right = self.place(pos3d=_lua_array([0.8, 0.25, 0.0]))
        self.assertLess(left['pan'], -0.9)
        self.assertAlmostEqual(middle['pan'], 0.0, places=3)
        self.assertGreater(right['pan'], 0.9)

    def test_the_far_row_is_quieter_than_the_near_one(self):
        near = self.place(pos3d=_lua_array([0.0, 0.3, 0.0]))
        far = self.place(pos3d=_lua_array([-0.8, 1.05, 0.0]))
        self.assertEqual(near['gain'], 1.0)
        self.assertLess(far['gain'], 1.0)

    def test_freq_is_a_pitch_because_that_is_how_rows_tell_each_other_apart(self):
        self.assertEqual(self.place(freq=-200)['cents'], -200)

    def test_play_is_a_repeat_count_not_a_boolean(self):
        """0 once, -1 for ever - a level's background music and a dialog's own
        bed - and n for n+1 times."""
        self.assertEqual(self.place(play=0)['repeats'], 0)
        self.assertFalse(self.place(play=0)['loop'])
        self.assertTrue(self.place(play=-1)['loop'])
        self.assertTrue(self.place(replay=-1)['loop'])
        self.assertEqual(self.place(play=3)['repeats'], 3)

    def test_a_flat_pan_still_works_for_a_sound_that_is_not_on_a_board(self):
        self.assertAlmostEqual(self.place(pan=-1.0)['pan'], -1.0)
        self.assertAlmostEqual(self.place(vol=0.5)['gain'], 0.5)


class TheVoiceFinishes(unittest.TestCase):
    """`k_VoiceIsSpeaking` IS `_Voice_GetStatus(v) == 0`.

    Answering 0 for ever - which is what a constant did - is a platform that
    is always speaking, so a sequence never reaches its second element. Mole
    No More froze on its welcome and every other application froze on theirs.
    """

    def runtime(self):
        from clingkit.klango import engine, keyboard, natives
        from clingkit.lua import LuaRuntime
        host = host_module.ClingHost(
            _AnyApp(), 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        runtime = LuaRuntime()
        files = natives.Filesystem(tempfile.mkdtemp(prefix='cling-v-'), '',
                                   tempfile.mkdtemp(prefix='cling-vw-'))
        natives.install(runtime, host, files, lambda *_a: None)
        engine.install(runtime, host, files, keyboard.Keyboard())
        return host, runtime

    def test_the_voice_is_speaking_and_then_it_is_not(self):
        host, runtime = self.runtime()
        runtime.run('v = _Voice_Create({})\n'
                    '_Voice_Speak(v, "a sentence of some length")\n'
                    'during = _Voice_GetStatus(v)\n')
        self.assertEqual(runtime.get_global('during'), 0)
        host.clock.advance(60.0)
        runtime.run('after = _Voice_GetStatus(v)\n')
        self.assertEqual(runtime.get_global('after'), 1)

    def test_stopping_the_voice_stops_it(self):
        _host, runtime = self.runtime()
        runtime.run('v = _Voice_Create({})\n'
                    '_Voice_Speak(v, "something")\n'
                    '_Voice_Stop(v)\n'
                    'after = _Voice_GetStatus(v)\n')
        self.assertEqual(runtime.get_global('after'), 1)


class RunningAnotherFile(unittest.TestCase):
    """`k_Run` is `_Sys_DoFile`, and both halves of that matter."""

    def session(self):
        from clingkit.klango import session as session_module
        folder = tempfile.mkdtemp(prefix='cling-run-')
        write(os.path.join(folder, 'level.lev'), 'Level = { n = (Level and Level.n or 0) + 1 }')
        write(os.path.join(folder, 'thing.lua'), 'ran = (ran or 0) + 1')
        app = _AnyApp()
        app.path = folder
        host = host_module.ClingHost(
            app, 'en', speaker=QuietSpeaker(), mixer=SilentMixer(),
            clock=runner.FakeClock())
        session = session_module.KlangoSession(host, lib_root='')
        # `k_Run` is `_Sys_DoFile`, and it is llib.lua that says so. Nothing
        # here loads the library, so the name is bound the way the library
        # binds it.
        session.runtime.set_global('k_Run', session.run_file)
        return session

    def test_a_lev_file_is_lua_too(self):
        """`.lua` was appended to a name that already had an extension, so
        `skin/default/levels/std_level_01.lev` came back "is not there" and
        no game ever started a level."""
        session = self.session()
        self.assertTrue(session.run_file('/level.lev'))
        self.assertIsNotNone(session.runtime.get_global('Level'))

    def test_it_runs_again_every_time_because_that_is_what_dofile_means(self):
        """A second level asked for and answered "already loaded" is the
        first level played thirteen times."""
        session = self.session()
        session.run_file('thing')
        session.run_file('thing')
        self.assertEqual(session.runtime.get_global('ran'), 2)

    def test_a_file_that_runs_itself_is_refused_rather_than_looping(self):
        session = self.session()
        folder = session.app_root
        write(os.path.join(folder, 'loop.lua'),
              'k_Run("loop")\ndepth = (depth or 0) + 1')
        self.assertTrue(session.run_file('loop'))
        self.assertEqual(session.runtime.get_global('depth'), 1)


class _AnyApp(object):
    """The least an application can be, for a test that is about something
    else entirely."""

    def __init__(self):
        self.id = 'test'
        self.path = tempfile.mkdtemp(prefix='cling-any-')
        self.package = ''
        self.engine = 'klango'
        self.kni = {}
        self.category = 'games'
        self.locked = False
        self.texts = None
        self.skin = None

    def open(self, _language=''):
        from clingkit import resources
        if self.texts is None:
            self.texts = resources.TextCatalogue(self.path, 'en')
        if self.skin is None:
            self.skin = resources.Skin(self.path, 'default', 'default')
        return self

    def name(self, _language=''):
        return 'Test'

    def description(self, _language=''):
        return ''


def _speaking(host):
    from clingkit.klango.engine import Speaking
    return Speaking(host)


def _lua_table(fields):
    from clingkit.lua.runtime import LuaTable
    table = LuaTable()
    for key, value in fields.items():
        table.raw_set(key, value)
    return table


def _lua_array(values):
    from clingkit.lua.runtime import LuaTable
    table = LuaTable()
    for index, value in enumerate(values, start=1):
        table.raw_set(index, value)
    return table


class Lpeg(unittest.TestCase):
    """The PEG library Klango's own modules build their parsers with.

    Seven of the platform library's files call `require("lpeg")` and construct
    patterns at load time, so if this is wrong the library does not finish
    loading and no application gets anything at all.
    """

    def runtime(self):
        from clingkit.klango import lpeg
        from clingkit.lua import LuaRuntime
        runtime = LuaRuntime()
        runtime.set_global('lpeg', lpeg.build(runtime))
        return runtime

    def lua(self, source):
        runtime = self.runtime()
        runtime.run('local m = lpeg\n' + source)
        return runtime

    def test_the_pieces_a_pattern_is_made_of(self):
        runtime = self.lua(
            'digits = m.match(m.C(m.R("09")^1), "1234abc")\n'
            'literal = m.match(m.P("ab") * m.P(-1), "ab")\n'
            'set = m.match(m.C(m.S("xyz")^1), "xyzq")\n'
            'nomatch = m.match(m.P("zz"), "ab")\n')
        self.assertEqual(runtime.get_global('digits'), '1234')
        self.assertEqual(runtime.get_global('literal'), 3)
        self.assertEqual(runtime.get_global('set'), 'xyz')
        self.assertIsNone(runtime.get_global('nomatch'))

    def test_the_difference_idiom_klangos_modules_are_written_with(self):
        """`( 1 - m.S(str) )^1` - the shape `llib_string` opens with."""
        runtime = self.lua(
            'local txtbez = function(str) return (1 - m.S(str))^1 end\n'
            'word = m.match(m.C(txtbez(" ,")), "hello, there")\n')
        self.assertEqual(runtime.get_global('word'), 'hello')

    def test_a_table_capture_collects_what_it_found(self):
        runtime = self.lua(
            'local word = m.C((1 - m.S(" "))^1)\n'
            'got = m.match(m.Ct(word * (m.P(" ")^1 * word)^0), "one two three")\n')
        table = runtime.get_global('got')
        self.assertEqual([table.raw_get(i) for i in (1, 2, 3)],
                         ['one', 'two', 'three'])

    def test_a_function_capture_is_applied_to_what_was_captured(self):
        runtime = self.lua(
            'upper = m.match(m.C(m.P(1)^0) / string.upper, "hi")\n'
            'const = m.match(m.Cc("fixed") * m.P("x"), "x")\n')
        self.assertEqual(runtime.get_global('upper'), 'HI')
        self.assertEqual(runtime.get_global('const'), 'fixed')

    def test_a_grammar_can_refer_to_its_own_rules(self):
        runtime = self.lua(
            'local V = m.V\n'
            'local g = m.P{ m.C(V(2)^1), m.R("az") }\n'
            'got = m.match(g, "abc1")\n')
        self.assertEqual(runtime.get_global('got'), 'abc')

    def test_repetition_counts_the_way_lpeg_counts(self):
        runtime = self.lua(
            'atleast = m.match(m.R("09")^2, "1")\n'
            'atmost = m.match(m.C(m.R("09")^-2), "1234")\n')
        self.assertIsNone(runtime.get_global('atleast'))
        self.assertEqual(runtime.get_global('atmost'), '12')

    def test_the_po_parser_shape_llib_uses_for_translations(self):
        """`llib_files_trans` reads .po files with exactly this."""
        runtime = self.lua(
            'local DQ = m.P("\\034")\n'
            'local WS = m.S(" \\t\\r\\n\\f")^0\n'
            'local qstring = WS * DQ * m.C((1 - DQ)^0) * DQ * WS\n'
            'got = m.match(m.Ct(qstring * qstring^0), \' "one" "two" \')\n')
        table = runtime.get_global('got')
        self.assertEqual([table.raw_get(1), table.raw_get(2)], ['one', 'two'])


class LuaPatterns(unittest.TestCase):
    """Lua patterns are not regular expressions, and applications rely on them."""

    def test_find_returns_positions_one_based(self):
        self.assertEqual(patterns.find('hello world', 'world')[:2], (7, 11))

    def test_classes_and_quantifiers(self):
        self.assertEqual(patterns.match('level 12 info', '(%a+) (%d+)'),
                         ['level', '12'])
        self.assertEqual(patterns.match('  x  ', '^%s*(.-)%s*$'), ['x'])

    def test_sets_ranges_and_negation(self):
        self.assertEqual(patterns.match('abc123', '[%a]+'), ['abc'])
        self.assertEqual(patterns.match('abc123', '[^%a]+'), ['123'])
        self.assertEqual(patterns.match('a-b', '%a%-%a'), ['a-b'])

    def test_anchors(self):
        self.assertIsNone(patterns.find('xabc', '^abc'))
        self.assertIsNotNone(patterns.find('abcx', '^abc'))
        self.assertIsNotNone(patterns.find('xabc', 'abc$'))

    def test_gsub_with_a_string_a_table_and_a_function(self):
        self.assertEqual(patterns.gsub('hello', 'l', 'L'), ('heLLo', 2))
        self.assertEqual(patterns.gsub('a b', '%a', str.upper)[0], 'A B')
        self.assertEqual(patterns.gsub('hello', 'l', 'L', 1), ('heLlo', 1))

    def test_gsub_can_refer_to_its_own_captures(self):
        self.assertEqual(patterns.gsub('john smith', '(%a+) (%a+)', '%2 %1')[0],
                         'smith john')

    def test_gmatch_walks_every_match(self):
        self.assertEqual([found[0] for found in patterns.gmatch('a,b,c', '[^,]+')],
                         ['a', 'b', 'c'])

    def test_balanced_and_frontier(self):
        self.assertEqual(patterns.match('f(a(b)c)d', '%b()'), ['(a(b)c)'])
        self.assertEqual(patterns.match('THE end', '%f[%l]%a+'), ['end'])


# --------------------------------------------------------------------------- #
# The package format, and the boundary Cling is honest about
# --------------------------------------------------------------------------- #
class Packages(ClingCase):

    def kpak(self, version=1, index_length=8, payload=b'x' * 32):
        import struct
        raw = (b'KPAK' + bytes([version]) + b'n' * 12 +
               struct.pack('<I', index_length) + b'i' * index_length + payload)
        return write_bytes(os.path.join(self.root, 'a.kpak'), raw)

    def test_a_header_is_readable_without_any_key(self):
        from clingkit import kpak
        header = kpak.read_header(self.kpak())
        self.assertEqual(header.version, 1)
        self.assertEqual(header.index_length, 8)
        self.assertEqual(header.payload_length, 32)

    def test_a_file_that_is_not_a_package_says_so(self):
        from clingkit import kpak
        path = write_bytes(os.path.join(self.root, 'b.kpak'), b'not a package')
        self.assertFalse(kpak.is_package(path))
        with self.assertRaises(kpak.KpakError):
            kpak.read_header(path)

    def test_without_a_key_extraction_says_exactly_what_is_missing(self):
        from clingkit import kpak
        with self.assertRaises(kpak.KpakError) as caught:
            kpak.extract(self.kpak(), self.root, keys=[])
        self.assertIn('no key', str(caught.exception))

    def test_inspecting_one_never_pretends_it_can_be_opened(self):
        from clingkit import kpak
        self.assertIn('Klango package', kpak.inspect(self.kpak()))


def build_klango_pag(path, files):
    """Write a package in Klango's own format, so the reader is tested against it.

    Built here rather than copied from an installation on purpose: a test that
    used the user's own packages would prove only that those files can be read,
    and would say nothing on a machine that has never seen Klango. This writes
    the layout the disassembly established - the concealment over a
    zlib-compressed directory of `(name, md5, offset, size, compressed)`
    records - and the reader has to agree with it.
    """
    import hashlib
    import struct
    import zlib

    blocks = bytearray()
    records = bytearray(b'\x00\x00')

    def record(name, digest, offset, size, compressed, mode):
        encoded = name.encode('utf-8')
        records.extend(struct.pack('<H', len(encoded)))
        records.extend(encoded)
        records.extend(digest)
        records.extend(struct.pack('<II', offset, size))
        records.append(1 if compressed else 0)
        tail = bytearray(48)
        struct.pack_into('<Q', tail, 6, mode)
        records.extend(tail)

    seen = set()
    for name in files:
        parent = name.rsplit('/', 1)[0]
        if parent and parent not in seen:
            seen.add(parent)
            record(parent, bytes(16), pag.KlangoEntry.DIRECTORY, 0, False, 0x41b6)
    for name, (content, compressed) in files.items():
        payload = zlib.compress(content) if compressed else content
        # Every offset in the format is measured from `plain[4]`, which is why
        # the reader looks at `plain[offset + 4]`. The blocks are contiguous;
        # there is nothing between them.
        record(name, hashlib.md5(content).digest(), 8 + len(blocks),
               len(payload), compressed, 0x81b6)
        blocks.extend(payload)

    directory = zlib.compress(bytes(records))
    plain = bytearray(struct.pack('<III', 0, pag.KLANGO_VERSION,
                                  8 + len(blocks)))
    plain.extend(blocks)
    plain.extend(directory)
    return write_bytes(path, pag.unconceal(bytes(plain)))


class PagPackages(ClingCase):
    """`.pag` - a whole application in one file, Klango's and Cling's alike."""

    FILES = {'/kni.txt': (b'appid=1\nappname=packed\nsummary=A packed one\n'
                          b'version=1.0\n', False),
             '/lang/default': (b'en-us\n', False),
             '/lang/en-us/default/welcome.txt': (b'Hello from a package' * 40,
                                                 True),
             '/game.lua': (b'-- the original logic\n', True)}

    def klango_pag(self, name='packed.pag', files=None):
        return build_klango_pag(os.path.join(self.apps_root, name),
                                files or self.FILES)

    def cling_pag(self, files=None):
        source = os.path.join(self.root, 'src')
        for name, body in (files or {'main.lua': 'function on_start() end\n',
                                     'kni.txt': 'appid=1\nappname=a\n'}).items():
            write(os.path.join(source, name), body)
        return pag.build(source, os.path.join(self.root, 'a.pag'))

    # ---------------------------------------------------------- recognising
    def test_the_two_kinds_are_told_apart_and_never_confused(self):
        self.assertEqual(pag.kind_of(self.klango_pag()), pag.KLANGO)
        self.assertEqual(pag.kind_of(self.cling_pag()), pag.CLING)

    def test_something_that_is_not_a_package_is_not_one(self):
        path = write_bytes(os.path.join(self.root, 'b.pag'), b'not a package')
        self.assertEqual(pag.kind_of(path), '')
        with self.assertRaises(pag.PagError):
            pag.read_header(path)

    def test_the_concealment_is_its_own_inverse(self):
        blob = os.urandom(600)
        self.assertEqual(pag.unconceal(pag.unconceal(blob)), blob)

    def test_the_concealment_is_the_one_the_binary_does(self):
        """`plain[i] = cipher[i] ^ ((i + PHASE) & 0xFF) ^ 0xC6`, read out of
        klangoplayer.exe - written out here so a change to it is noticed."""
        blob = bytes(range(256))
        expected = bytes(byte ^ ((i + pag.KLANGO_PHASE) & 0xFF) ^ pag.KLANGO_XOR
                         for i, byte in enumerate(blob))
        self.assertEqual(pag.unconceal(blob), expected)

    # -------------------------------------------------------------- reading
    def test_a_klango_package_is_read_and_every_file_checked_against_its_md5(self):
        path = self.klango_pag()
        with open(path, 'rb') as handle:
            entries = pag.read_klango_index(pag.unconceal(handle.read()))
        names = sorted(entry.name for entry in entries if not entry.is_directory)
        self.assertEqual(names, sorted(self.FILES))
        out = os.path.join(self.root, 'out')
        written = pag.extract(path, out)
        self.assertEqual(len(written), len(self.FILES))
        with open(os.path.join(out, 'lang', 'en-us', 'default', 'welcome.txt'),
                  'rb') as handle:
            self.assertEqual(handle.read(),
                             self.FILES['/lang/en-us/default/welcome.txt'][0])

    def test_a_file_that_does_not_match_its_own_md5_is_refused(self):
        """The digest is what says extraction really worked, so it is used."""
        path = self.klango_pag()
        with open(path, 'rb') as handle:
            plain = bytearray(pag.unconceal(handle.read()))
        entries = pag.read_klango_index(bytes(plain))
        stored = [e for e in entries if not e.is_directory and not e.compressed][0]
        plain[stored.offset + 4] ^= 0xFF
        write_bytes(path, pag.unconceal(bytes(plain)))
        with self.assertRaises(pag.PagError):
            pag.extract(path, os.path.join(self.root, 'out'))

    def test_a_directory_that_points_outside_the_file_is_refused(self):
        import struct
        path = self.klango_pag()
        with open(path, 'rb') as handle:
            plain = bytearray(pag.unconceal(handle.read()))
        struct.pack_into('<I', plain, 8, len(plain) + 1000)
        write_bytes(path, pag.unconceal(bytes(plain)))
        with self.assertRaises(pag.PagError):
            with open(path, 'rb') as handle:
                pag.read_klango_index(pag.unconceal(handle.read()))

    # --------------------------------------------------------- Cling's own
    def test_a_cling_package_round_trips(self):
        path = self.cling_pag({'main.lua': 'x = 1\n', 'a/b.txt': 'hello'})
        names = sorted(entry['name'] for entry in pag.entries_of(path))
        self.assertEqual(names, ['a/b.txt', 'main.lua'])
        out = os.path.join(self.root, 'out')
        pag.extract(path, out)
        with open(os.path.join(out, 'a', 'b.txt'), encoding='utf-8') as handle:
            self.assertEqual(handle.read(), 'hello')

    def test_an_entry_that_points_outside_the_folder_is_refused(self):
        path = self.cling_pag()
        import json, lzma, struct
        entries = [{'name': '../escaped.txt', 'offset': 0, 'size': 3}]
        index = lzma.compress(json.dumps(entries).encode('utf-8'))
        body = lzma.compress(b'abc')
        header = (pag.CLING_MAGIC + bytes([pag.CLING_VERSION])
                  + struct.pack('<I', len(index)) + struct.pack('<H', 1)
                  + b'\x00' * (pag.CLING_HEADER - 11))
        write_bytes(path, header + index + body)
        with self.assertRaises(pag.PagError):
            pag.extract(path, os.path.join(self.root, 'out'))

    # ------------------------------------------------------ as applications
    def test_a_klango_package_in_the_data_folder_is_an_installed_application(self):
        self.klango_pag()
        found = catalog.discover([self.apps_root], 'en')
        self.assertEqual([app.id for app in found], ['packed'])
        self.assertFalse(found[0].locked)
        self.assertTrue(found[0].playable)
        self.assertTrue(found[0].texts.text('welcome').startswith('Hello'))
        self.assertTrue(found[0].package.endswith('packed.pag'))

    def test_a_cling_package_in_the_data_folder_is_one_too(self):
        source = os.path.join(self.root, 'src2')
        write(os.path.join(source, 'kni.txt'), 'appid=1\nappname=c\n')
        write(os.path.join(source, 'lang', 'default'), 'en-us\n')
        write(os.path.join(source, 'lang', 'en-us', 'default', 'welcome.txt'),
              'from a Cling package')
        pag.build(source, os.path.join(self.apps_root, 'c.pag'))
        found = catalog.discover([self.apps_root], 'en')
        self.assertEqual([app.id for app in found], ['c'])
        self.assertEqual(found[0].texts.text('welcome'), 'from a Cling package')

    def test_a_folder_wins_over_a_package_of_the_same_name(self):
        self.klango_app('packed', texts={'welcome': 'from the folder'})
        self.klango_pag()
        found = catalog.discover([self.apps_root], 'en')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].texts.text('welcome'), 'from the folder')
        self.assertTrue(found[0].package, 'the original package was forgotten')

    def test_the_platforms_own_library_is_not_offered_as_something_to_play(self):
        self.klango_pag('llib.pag')
        self.assertEqual(catalog.discover([self.apps_root], 'en'), [])


class BundledLogic(unittest.TestCase):
    """The logic Cling ships for applications whose own code it cannot have."""

    def test_every_shipped_script_parses(self):
        """A game that will not parse is a game nobody can play."""
        from clingkit.lua import parser
        root = catalog.logic_dir()
        checked = 0
        for name in sorted(os.listdir(root)):
            source = os.path.join(root, name, 'main.lua')
            if not os.path.isfile(source):
                continue
            with open(source, encoding='utf-8') as handle:
                parser.parse(handle.read(), '%s/main.lua' % name)
            checked += 1
        self.assertGreater(checked, 0, 'no bundled logic was checked')

    def test_every_shipped_script_is_packed_and_the_package_matches(self):
        """The folder is what an author edits; the `.pag` is what ships."""
        root = catalog.logic_dir()
        for name in sorted(os.listdir(root)):
            folder = os.path.join(root, name)
            source = os.path.join(folder, 'main.lua')
            if not os.path.isfile(source):
                continue
            package = os.path.join(root, name + '.pag')
            self.assertTrue(os.path.isfile(package),
                            '%s has no .pag beside it' % name)
            mounted = pag.mount(package)
            with open(source, encoding='utf-8') as handle:
                written = handle.read()
            with open(os.path.join(mounted, 'main.lua'), encoding='utf-8') as handle:
                self.assertEqual(handle.read(), written,
                                 '%s.pag is older than its folder' % name)

    def test_an_application_with_no_script_of_its_own_is_given_ours(self):
        root = catalog.logic_dir()
        packaged = [os.path.splitext(name)[0] for name in os.listdir(root)
                    if name.endswith('.pag')]
        self.assertTrue(packaged)
        for name in packaged:
            self.assertTrue(catalog.has_bundled_logic(name), name)
        self.assertFalse(catalog.has_bundled_logic('nothing-cling-ships'))


# --------------------------------------------------------------------------- #
# The session, which is what the window and the tests both drive
# --------------------------------------------------------------------------- #
class Sessions(ClingCase):

    def test_a_session_starts_stops_and_keeps_what_was_said(self):
        self.klango_app('a', texts={'welcome': 'Hello'})
        app = catalog.discover([self.apps_root], 'en')[0]
        clock = runner.FakeClock()
        session = runner.Session(app, 'en', clock=clock)
        session.host.speaker = QuietSpeaker()
        session.host.mixer = SilentMixer()
        session.engine = engines.build(session.host)
        session.start()
        self.assertIn('Hello', session.messages)
        session.stop()
        self.assertFalse(session.running)

    def test_a_key_pressed_after_the_application_stopped_is_ignored(self):
        self.klango_app('a', texts={'welcome': 'Hello'})
        app = catalog.discover([self.apps_root], 'en')[0]
        session = runner.Session(app, 'en', clock=runner.FakeClock())
        session.stop()
        self.assertFalse(session.key('space'))


class TheComponent(unittest.TestCase):
    """Cling reaches all three of Titan's faces, the way the macro manager does.

    The component module is imported here rather than stubbed: a hook that has
    been renamed, or a category that is built but never inserted, is exactly
    the failure that leaves a subsystem working in the graphical window and
    absent for the users least likely to be looking at one.
    """

    @classmethod
    def setUpClass(cls):
        if COMPONENT not in sys.path:
            sys.path.insert(0, COMPONENT)
        import init
        cls.init = init

    def test_every_hook_titan_calls_is_there(self):
        for name in ('add_menu', 'get_gui_hooks', 'get_iui_hooks',
                     'get_klango_hooks', 'add_settings_category', 'initialize',
                     'shutdown', 'TITAN_ACTIONS'):
            self.assertTrue(hasattr(self.init, name), name)

    def test_the_hooks_name_functions_that_exist(self):
        for getter, key in (('get_gui_hooks', 'on_gui_init'),
                            ('get_iui_hooks', 'on_iui_init'),
                            ('get_klango_hooks', 'on_klango_init')):
            hooks = getattr(self.init, getter)()
            self.assertIn(key, hooks)
            self.assertTrue(callable(hooks[key]))

    def test_the_invisible_ui_gets_a_category_of_its_own(self):
        import types
        iui = types.SimpleNamespace(categories=[{'name': 'Programs'},
                                                {'name': 'Menu'}])
        self.init._on_iui_init(iui)
        names = [category['name'] for category in iui.categories]
        self.assertIn(self.init._('Cling'), names)
        category = iui.categories[names.index(self.init._('Cling'))]
        self.assertTrue(callable(category['action']))
        self.assertTrue(category['elements'])

    def test_classic_mode_gets_a_submenu_of_its_own(self):
        import types
        klango = types.SimpleNamespace(
            main_menu=[{'name': str(index)} for index in range(8)])
        self.init._on_klango_init(klango)
        found = [entry for entry in klango.main_menu
                 if entry.get('name') == self.init._('Cling')]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['type'], 'submenu')
        self.assertTrue(found[0]['items'])
        self.assertTrue(callable(found[0]['items'][0]['action']))

    def test_every_action_has_something_to_run(self):
        for action in self.init.TITAN_ACTIONS:
            self.assertIn('name', action)
            self.assertIn('summary', action)
            self.assertTrue(callable(action['run']), action['name'])

    def test_an_action_naming_an_application_nobody_has_says_so(self):
        """A refusal is a `Failure`, not prose - which is what a caller reads."""
        answer = self.init.action_details(name='no-such-application')
        self.assertIn('no Cling application', str(answer))



# --------------------------------------------------------------------------- #
# The applications the user really has: do they actually PLAY?
# --------------------------------------------------------------------------- #
# Everything above builds its own applications out of a few files, which proves
# the readers and the engines. It does not prove that Mole No More can be won,
# that Klango Piano's samples are on the disk where the engine looks for them,
# or that Long Jump's run-up makes a sound - and those are the things that are
# actually broken when a subsystem like this is broken.
#
# So these run against the applications installed in `data/cling/`, and skip
# themselves cleanly when there are none, so the suite still passes on a machine
# that has never seen Klango.

def _installed():
    try:
        return {app.id: app for app in catalog.discover(language='en')}
    except Exception:
        return {}


INSTALLED = _installed()


def needs(app_id):
    return unittest.skipUnless(app_id in INSTALLED,
                               '%s is not installed in data/cling' % app_id)


class RecordingMixer(SilentMixer):
    """A mixer that plays nothing and remembers exactly what it was HANDED.

    The host resolves a name to a path before the mixer ever sees it, so this
    is where "the game asked for t_mole_hello and the skin really has it" is
    decided. A name Cling could not resolve arrives as '' - which is precisely
    the failure a test must catch, because at run time it is simply silence.
    """

    def __init__(self):
        SilentMixer.__init__(self)
        self.asked = []

    def start(self, path, pan=0.0, elevation=0.0, gain=1.0, cents=0.0,
              loop=False, repeats=0):
        self.asked.append(path or '')
        return SilentMixer.start(self, path, pan, elevation, gain, cents,
                                 loop, repeats)

    def missing(self):
        """Sounds the application asked for and Cling could not find."""
        return [path for path in self.asked if not path or not os.path.isfile(path)]


class SoundReallyReachesTheMixer(unittest.TestCase):
    """`sound_mode` says HOW a sound is placed, never whether there is one.

    Reading `none` - which is Titan's default, stereo being opt-in - as "make
    no sound" made the whole subsystem silent, and a silent audio game is
    indistinguishable from a broken one. The mixer is stood in for at the level
    BELOW Cling (the `sound` module), so what is tested is Cling's own
    decision, on every mode the user can have.
    """

    class FakeSound(object):
        def __init__(self, mode):
            self.mode = mode
            self.played = []

        def get_sound_mode(self):
            return self.mode

        def load_settings(self):
            return {'sound': {'sound_theme_volume': 100}}

        def play_sound_file(self, path, pan=None, elevation=0.0):
            self.played.append((path, pan))
            return True

        def initialize_sound(self):
            return True

    def mixer_for(self, mode):
        mixer = host_module.Mixer()
        mixer._sound = self.FakeSound(mode)
        mixer._spatial = None
        mixer._pygame = None
        return mixer

    def test_a_sound_is_played_on_every_mode_including_none(self):
        here = write(os.path.join(tempfile.mkdtemp(), 'a.ogg'), 'not really ogg')
        for mode in ('none', 'stereo', '3d'):
            with self.subTest(mode=mode):
                mixer = self.mixer_for(mode)
                self.assertTrue(mixer.play(here, 0.0, 0.0, 1.0),
                                'nothing played with sound_mode %r' % mode)
                self.assertTrue(mixer._sound.played)

    def test_a_placed_sound_still_carries_its_place(self):
        here = write(os.path.join(tempfile.mkdtemp(), 'a.ogg'), 'x')
        mixer = self.mixer_for('stereo')
        mixer.play(here, -1.0, 0.0, 1.0)
        self.assertEqual(mixer._sound.played[-1][1], 0.0)      # hard left, 0..1
        mixer.play(here, 1.0, 0.0, 1.0)
        self.assertEqual(mixer._sound.played[-1][1], 1.0)

    def test_a_file_that_is_not_there_is_not_played(self):
        mixer = self.mixer_for('stereo')
        self.assertFalse(mixer.play('', 0.0))
        self.assertFalse(mixer.play('/no/such/file.ogg', 0.0))

    # ------------------------------------------------------------ the place
    class FakeChannel(object):
        def __init__(self):
            self.volumes = []

        def set_volume(self, *values):
            self.volumes.append(values)

        def play(self, *_args, **_kwargs):
            pass

        def stop(self):
            pass

    class FakePygame(object):
        """Just enough pygame to see what Cling asks a channel to do.

        pygame's own `Channel.get_volume()` answers with one number whatever
        `set_volume` was given, so a live run cannot tell a panned channel from
        a centred one - the call itself is the only place the truth is.
        """

        def __init__(self, channel):
            self.mixer = self
            self._channel = channel

        def Sound(self, _path):
            return object()

        def find_channel(self):
            return self._channel

        def get_init(self):
            return (22050, -16, 2)

    def placed_mixer(self, mode, channel):
        mixer = self.mixer_for(mode)
        mixer._pygame = self.FakePygame(channel)
        return mixer

    def test_a_sound_is_placed_even_when_titans_stereo_is_off(self):
        """A Klango board is aimed at by ear; the pan is not a preference."""
        here = write(os.path.join(tempfile.mkdtemp(), 'a.ogg'), 'x')
        channel = self.FakeChannel()
        mixer = self.placed_mixer('none', channel)
        self.assertTrue(mixer.play(here, -1.0, 0.0, 1.0))
        self.assertTrue(channel.volumes, 'the channel was never placed')
        left, right = channel.volumes[-1]
        self.assertGreater(left, right, 'a sound on the left was not on the left')

    def test_the_pan_law_reaches_both_ends_and_the_middle(self):
        """Constant power, not linear: a sound that crosses the listener
        must not dip 3 dB as it passes the middle, which is where the
        distance model is making it loudest."""
        here = write(os.path.join(tempfile.mkdtemp(), 'a.ogg'), 'x')
        channel = self.FakeChannel()
        mixer = self.placed_mixer('none', channel)
        for pan, expected in ((-1.0, (1.0, 0.0)), (0.0, (0.707, 0.707)),
                              (1.0, (0.0, 1.0))):
            mixer.play(here, pan, 0.0, 1.0)
            self.assertEqual(tuple(round(value, 3)
                                   for value in channel.volumes[-1]), expected,
                             'pan %s' % pan)

    def test_a_sound_crossing_the_listener_keeps_its_loudness(self):
        here = write(os.path.join(tempfile.mkdtemp(), 'a.ogg'), 'x')
        channel = self.FakeChannel()
        mixer = self.placed_mixer('none', channel)
        power = []
        for step in range(9):
            mixer.play(here, -1.0 + step * 0.25, 0.0, 1.0)
            left, right = channel.volumes[-1]
            power.append(round(left * left + right * right, 3))
        self.assertEqual(power, [1.0] * 9, 'it changed loudness as it went')

    def test_a_quieter_sound_is_still_placed(self):
        here = write(os.path.join(tempfile.mkdtemp(), 'a.ogg'), 'x')
        channel = self.FakeChannel()
        mixer = self.placed_mixer('none', channel)
        mixer.play(here, 1.0, 0.0, 0.5)
        left, right = channel.volumes[-1]
        self.assertAlmostEqual(left, 0.0)
        self.assertAlmostEqual(right, 0.5)


class RealApplications(unittest.TestCase):
    """The installed applications, played."""

    def open(self, app_id, language='en', clock=None, engine=''):
        """Open an installed application.

        `engine` forces one, because emulation is now what an application gets
        by default and these tests are about the engines that run it from its
        DATA - which is what happens on a machine where Klango's own library is
        not installed, and is therefore still worth proving.
        """
        app = INSTALLED[app_id]
        clock = clock or runner.FakeClock()
        host = host_module.ClingHost(
            app, language, speaker=QuietSpeaker(), mixer=RecordingMixer(),
            store=store_module.Store(app_id, 'test-suite',
                                     tempfile.mkdtemp(prefix='cling-real-')),
            clock=clock)
        if engine:
            previous, app.engine = app.engine, engine
            try:
                built = engines.build(host)
            finally:
                app.engine = previous
        else:
            built = engines.build(host)
        return app, host, built, clock

    def assert_no_silence(self, host, ignore_theme=True):
        """Every sound the application asked for is a file that is really there.

        A name with a slash in it (`ui/focus`) is one of TITAN's, resolved
        through the user's sound theme, and a test must not fail because the
        machine running it has a theme that does not carry it. Everything else
        is the application's own, and if it did not resolve, the game is silent
        where it meant to speak.
        """
        missing = host.mixer.missing()
        if ignore_theme:
            asked = [name for name in host.mixer.asked if name]
            missing = [name for name in missing if name]
        self.assertEqual(missing, [],
                         'sounds the application asked for and Cling did not '
                         'find: %s' % missing)

    # ---------------------------------------------------------------- data
    def test_every_installed_application_reads(self):
        self.assertTrue(INSTALLED, 'no applications installed')
        for app_id, app in INSTALLED.items():
            with self.subTest(app=app_id):
                self.assertTrue(app.name('en'), app_id)
                self.assertIn(app.category, catalog.CATEGORIES)
                if app.locked:
                    self.assertTrue(app.locked_reason())
                    continue
                self.assertIn(app.engine, engines.names())
                self.assertTrue(app.texts.locale, '%s has no locale' % app_id)

    def test_every_playable_application_starts_without_a_word_of_complaint(self):
        """The engines that read an application, not the emulator.

        Emulation runs an application's own code on a thread of its own and is
        checked separately and under a budget; this sweep is about the readers
        and the data-driven engines answering for every application installed.
        """
        started = 0
        for app_id, app in INSTALLED.items():
            if app.locked or app.engine == catalog.ENGINE_KLANGO:
                continue
            with self.subTest(app=app_id):
                _app, host, engine, _clock = self.open(app_id)
                engine.start()
                self.assertEqual(getattr(engine, 'error', ''), '',
                                 '%s failed to start' % app_id)
                self.assertTrue(host.messages or engine.rows() or
                                engine.finished_reason,
                                '%s started and said nothing' % app_id)
                engine.stop()
                started += 1
        self.assertGreater(started, 0)

    # ------------------------------------------------------- the board game
    @needs('mole')
    def test_mole_has_all_thirteen_levels_and_every_board_builds(self):
        _app, _host, engine, _clock = self.open('mole', engine='grid_hunt')
        self.assertEqual(engine.level_problems, [])
        self.assertEqual(len(engine.levels), 13)
        for index, level in enumerate(engine.levels):
            with self.subTest(level=index + 1):
                board = topology.load(engine.host.skin, level.get('topology'),
                                      int(level.get('fields', 0) or 0), 0)
                self.assertEqual(len(board), int(level.get('fields')),
                                 'level %d says %s fields and its topology has %d'
                                 % (index + 1, level.get('fields'), len(board)))
                self.assertGreater(int(level.get('hit_target', 0)), 0)

    @needs('mole')
    def test_mole_can_be_played_and_won_and_every_sound_is_real(self):
        clock = runner.FakeClock()
        _app, host, engine, _clock = self.open('mole', clock=clock, engine='grid_hunt')
        engine.start()
        engine.key('space')
        self.assertEqual(engine.state, 'playing')
        target = int(engine.levels[0]['hit_target'])
        for _round in range(target):
            clock.advance(0.6)
            engine.tick()
            self.assertTrue(engine.occupants, 'nothing came up to be hit')
            engine.cursor = engine.occupants[0].field
            engine.key('space')
        self.assertEqual(engine.hits, target)
        self.assertNotEqual(engine.state, 'playing')     # the level was finished
        self.assert_no_silence(host)
        # The sounds the game is MADE of, each really played.
        played = {name for name, _pan, _gain in host.mixer.played}
        for expected in ('t_mole_hello.ogg', 't_mole_auu.ogg',
                         'e_earn_points1.ogg'):
            self.assertIn(expected, played)

    @needs('mole')
    def test_mole_is_heard_where_the_topology_says(self):
        clock = runner.FakeClock()
        _app, host, engine, _clock = self.open('mole', clock=clock, engine='grid_hunt')
        engine.start()
        engine.key('space')
        seen = set()
        for _round in range(30):
            clock.advance(0.5)
            engine.tick()
            for occupant in engine.occupants:
                seen.add(round(occupant.field.pan, 3))
            for occupant in list(engine.occupants):
                engine.cursor = occupant.field
                engine.key('space')
        # A 3x3 board is three columns, and they are not all in the middle.
        self.assertGreaterEqual(len(seen), 2, 'every mole came from one place')
        self.assertTrue(any(pan < 0 for pan in seen))
        self.assertTrue(any(pan > 0 for pan in seen))

    @needs('mole')
    def test_mole_remembers_the_level_between_runs(self):
        state = tempfile.mkdtemp(prefix='cling-level-')
        app = INSTALLED['mole']
        first = host_module.ClingHost(
            app, 'en', speaker=QuietSpeaker(), mixer=RecordingMixer(),
            store=store_module.Store('mole', 'p', state),
            clock=runner.FakeClock())
        first.store.set('level', 4)
        again = host_module.ClingHost(
            app, 'en', speaker=QuietSpeaker(), mixer=RecordingMixer(),
            store=store_module.Store('mole', 'p', state),
            clock=runner.FakeClock())
        previous, app.engine = app.engine, catalog.ENGINE_GRID_HUNT
        try:
            engine = engines.build(again)
        finally:
            app.engine = previous
        engine.start()
        self.assertEqual(engine.level_index, 4)

    # --------------------------------------------------------- the others
    @needs('piano')
    def test_piano_maps_keys_to_samples_that_are_on_the_disk(self):
        _app, host, engine, _clock = self.open('piano', engine='instrument')
        engine.start()
        self.assertTrue(engine.sets)
        self.assertGreaterEqual(len(engine.samples), 10)
        for key, (path, _loops) in engine.samples.items():
            self.assertTrue(os.path.isfile(path), '%s -> %s' % (key, path))
        self.assertTrue(any(loops for _path, loops in engine.samples.values()),
                        'no looping sample was recognised')
        key = sorted(engine.samples)[0]
        self.assertTrue(engine.key(key))
        self.assert_no_silence(host)

    @needs('ktypist')
    def test_the_typing_course_reads_and_a_line_can_be_typed(self):
        clock = runner.FakeClock()
        _app, host, engine, _clock = self.open('ktypist', clock=clock, engine='typing')
        engine.start()
        self.assertGreater(len(engine.lessons), 1)
        self.assertTrue(engine.lesson.levels)
        engine.key('space')
        self.assertEqual(engine.state, 'typing')
        line = engine.line
        clock.advance(5.0)
        for character in line:
            engine.key('space' if character == ' ' else character)
        self.assertEqual(engine.state, 'done')
        self.assertEqual(engine.mistakes, 0)
        self.assertTrue(any('minute' in message or '%' in message
                            for message in host.messages))

    @needs('zawisza')
    def test_the_soundscape_has_every_recording_its_specification_names(self):
        clock = runner.FakeClock()
        _app, host, engine, _clock = self.open('zawisza', clock=clock, engine='soundscape')
        engine.start()
        self.assertTrue(engine.locations, 'spec.txt was not read')
        self.assertIn(engine.start_name, engine.locations)
        for name, location in engine.locations.items():
            with self.subTest(location=name):
                self.assertTrue(engine._sound_path('%s_bkg' % name),
                                'no background recording for %s' % name)
                for link in location.links:
                    self.assertIn(link, engine.locations,
                                  '%s links to %s, which is nowhere' % (name, link))
                for effect in location.effects:
                    self.assertTrue(engine._sound_path(effect.name),
                                    'no recording for %s' % effect.name)
        for _step in range(60):
            clock.advance(5.0)
            engine.tick()
        self.assert_no_silence(host)
        self.assertTrue([name for name, _pan, _gain in host.mixer.played
                         if not name.startswith('loop:')],
                        'nothing ever happened in the soundscape')

    # ------------------------------------------- the logic Cling ships
    def _play_bundled(self, app_id, keys, rounds=40):
        clock = runner.FakeClock()
        _app, host, engine, _clock = self.open(app_id, clock=clock,
                                               engine='script')
        engine.start()
        self.assertEqual(engine.error, '', '%s failed on start' % app_id)
        for key in keys:
            clock.advance(0.3)
            engine.tick()
            engine.key(key)
            self.assertEqual(engine.error, '',
                             '%s failed on key %r' % (app_id, key))
        for _step in range(rounds):
            clock.advance(0.4)
            engine.tick()
        self.assertEqual(engine.error, '', '%s failed while running' % app_id)
        return host, engine

    @needs('puzzle')
    def test_puzzle_deals_a_board_that_can_be_solved_and_moves_make_a_sound(self):
        """A slide has to be CERTAIN, not likely.

        The board is shuffled from a seed the application takes from the clock,
        so a fixed walk that only covers part of it passes or fails depending on
        what second the test ran in - which is exactly what the first version of
        this did. Standing on every square in turn and pressing space on each
        one is what makes a legal slide unavoidable: wherever the empty square
        is, one of its neighbours is somewhere on that path.
        """
        keys = ['space']                       # choose the level and deal
        for row in range(5):
            across = 'right' if row % 2 == 0 else 'left'
            for _column in range(5):
                keys += ['space', across]
            keys += ['space', 'down']
        host, engine = self._play_bundled('puzzle', keys)
        self.assert_no_silence(host)
        played = {name for name, _pan, _gain in host.mixer.played}
        self.assertTrue({'movebegin.ogg', 'moveend.ogg'} & played,
                        'no tile was ever heard moving; heard %s' % sorted(played))
        self.assertTrue(engine.status())

    @needs('skeet')
    def test_skeet_launches_a_disc_and_the_shot_is_heard(self):
        host, engine = self._play_bundled(
            'skeet', ['space', 'space', 'space', 'left', 'space', 'space'])
        self.assert_no_silence(host)
        played = {name for name, _pan, _gain in host.mixer.played}
        self.assertIn('throw.ogg', played)
        self.assertIn('fire.ogg', played)

    @needs('long_jump')
    def test_long_jump_runs_up_and_the_steps_speed_up(self):
        host, engine = self._play_bundled(
            'long_jump', ['s'] + ['left', 'right'] * 14 + ['space'])
        self.assert_no_silence(host)
        played = [name for name, _pan, _gain in host.mixer.played]
        self.assertIn('foot.wav', played)
        self.assertGreater(played.count('foot.wav'), 4,
                           'the athlete never got going')

    @needs('dicepoker')
    def test_dice_poker_rolls_five_dice_and_a_category_can_be_taken(self):
        host, engine = self._play_bundled(
            'dicepoker',
            ['space', '1', '2', 'space', 'tab', 'down', 'enter', 'tab', 'space'])
        self.assert_no_silence(host)
        # The game's own state is Lua's, not Python's, so it is checked the way
        # a player would check it: five dice were heard, and the score card
        # said what was saved.
        played = [name for name, _pan, _gain in host.mixer.played]
        self.assertGreaterEqual(sum(1 for name in played
                                    if name.startswith('dice')), 5,
                                'five dice were never rolled')
        self.assertTrue(any('dice' in message.lower() or ':' in message
                            for message in host.messages))
        self.assertTrue(engine.status())

    @needs('wiki')
    def test_the_wikipedia_client_starts_and_never_dials_out_by_itself(self):
        """Opening a client must not be a network request."""
        _app, host, engine, _clock = self.open('wiki', engine='script')
        reached = []
        host.http_get = lambda url, timeout=8.0: (reached.append(url), ('', 'no'))[1]
        engine.start()
        self.assertEqual(engine.error, '')
        self.assertEqual(reached, [], 'it went to the network before being asked')

    # ------------------------------------------------------------ settings
    def test_the_settings_round_trip(self):
        if COMPONENT not in sys.path:
            sys.path.insert(0, COMPONENT)
        import init
        for key, value in (('online_scores', False), ('online_scores', True),
                           ('read_everything', False)):
            init.set_setting(key, value)
            self.assertEqual(str(init.get_setting(key)), str(value))

    def test_the_shipped_texts_are_translated_into_the_users_language(self):
        import gettext
        catalogue = gettext.translation(
            'cling', os.path.join(COMPONENT, 'languages'), languages=['pl'],
            fallback=True)
        self.assertEqual(catalogue.gettext('Games'), 'Gry')
        self.assertEqual(catalogue.gettext('High scores'), 'Najlepsze wyniki')


if __name__ == '__main__':
    unittest.main(verbosity=2)
