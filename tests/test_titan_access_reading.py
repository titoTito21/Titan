# -*- coding: utf-8 -*-
"""Titan Access reads menus, the task switcher, its own settings and a
ticked check box - and the keys the user named reach what they named.

    python tests/test_titan_access_reading.py

Every fault here was found by running the real engine headlessly with
printed speech and driving a classic menu, Alt+Tab, the virtual window,
the palette and a check box with injected keys (see the session notes in
`data/components/titan access/WHAT_TITAN_ACCESS_LACKS.md`). Nothing here
opens a window, speaks, plays a sound or reaches Titan.
"""

import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)


def _source(*parts):
    return io.open(os.path.join(COMPONENT, 'titan_access', *parts),
                   encoding='utf-8').read()


class _Obj:
    """A focus snapshot with just what a test names."""

    def __init__(self, role='button', name='', states=(), hwnd=0,
                 bounds=(0, 0, 0, 0), automation_id='', native=None,
                 value='', description='', class_name='', framework_id=''):
        self.role = role
        self.name = name
        self.states = set(states)
        self.hwnd = hwnd
        self.bounds = bounds
        self.automation_id = automation_id
        self.native = native
        self.value = value
        self.description = description
        self.class_name = class_name
        self.framework_id = framework_id
        self.help_text = ''
        self.level = 0
        self.pos_in_set = 0
        self.size_of_set = 0
        self.parameter = ''
        self.process_id = 0

    def has(self, state):
        return state in self.states


class _Named:
    def __init__(self, name):
        self.name = name


class _Adapted:
    """The shape the shared modules read, built by hand."""

    def __init__(self, role, name='', children=(), parent=None,
                 headers=()):
        self.role = _Named(role)
        self.name = name
        self.value = ''
        self.children = list(children)
        self.parent = parent
        self._headers = list(headers)
        self.windowText = ''
        self.states = set()

    @property
    def columnCount(self):
        return len(self._headers)

    def _getColumnHeader(self, index):
        return self._headers[index - 1] if 1 <= index <= len(self._headers) \
            else ''


# --------------------------------------------------------------------------- #
# The root cause: a five-element segment unpacked as two
# --------------------------------------------------------------------------- #
class AFiveElementSegmentDoesNotSilenceTheReader(unittest.TestCase):

    def test_split_segment_takes_any_length(self):
        from titan_access import accessible
        self.assertEqual(accessible.split_segment(('a', 4)), ('a', 4, 0, 0))
        self.assertEqual(accessible.split_segment(('a', -4, 0.0, 3, -2)),
                         ('a', -4, 3, -2))
        self.assertEqual(accessible.split_segment(('a',)), ('a', 0, 0, 0))

    def test_nothing_unpacks_a_segment_as_a_pair(self):
        """`_part` answers five elements once a class carries a rate, and
        every `for text, pitch in segments` then raised on the focus
        path - which is what silenced every menu item after the first
        and every row of the Alt+Tab switcher."""
        for name in ('engine.py', 'accessible.py', 'menu_tracker.py',
                     'context_presenter.py'):
            source = _source(name)
            for bad in ('for (t, p) in', 'for t, p in', 'for text, pitch in',
                        'for t, _p in', 'for text, _pitch in'):
                lines = [line for line in source.splitlines()
                         if bad in line and not line.strip().startswith('#')
                         and 'consumer used to write' not in line]
                self.assertEqual(lines, [], '%s still has %r' % (name, bad))

    def test_the_engine_carries_rate_and_volume_to_the_speech(self):
        source = _source('engine.py')
        at = source.index('def speak_segments(')
        block = source[at:source.index('\n    def ', at + 10)]
        self.assertIn('seg[3:5]', block)
        self.assertIn('gap_ms', block)


# --------------------------------------------------------------------------- #
# The keys the user named
# --------------------------------------------------------------------------- #
class TheKeysTheUserNamedReachWhatTheyNamed(unittest.TestCase):

    def _gestures(self):
        source = _source('engine.py')
        at = source.index('def _register_default_gestures(')
        return source[at:source.index('\n    def ', at + 10)]

    def test_insert_minus_is_the_virtual_window(self):
        block = self._gestures()
        self.assertIn('g.register("virtualWindow", "numpadsubtract"', block)
        self.assertIn('g.register("virtualWindow", "-"', block)
        # The old spec matched no key the hook ever produces.
        self.assertNotIn('"minus"', block)

    def test_insert_shift_space_is_the_palette(self):
        block = self._gestures()
        self.assertIn('g.register("commandPalette", "shift+space"', block)
        # And it is no longer on the key browse mode owns.
        self.assertNotIn('g.register("commandPalette", "space"', block)

    def test_insert_control_g_is_the_readers_settings_walked(self):
        block = self._gestures()
        self.assertIn('g.register("readerSettings", "control+g"', block)
        self.assertIn('def action_reader_settings_window(', _source('engine.py'))

    def test_the_touchpad_moved_to_shift(self):
        block = self._gestures()
        self.assertIn('g.register("trackpad", "shift+numpadsubtract"', block)

    def test_the_dial_does_not_take_insert_minus(self):
        """The hook says when the modifier is held, and only a bare NumPad
        minus is the dial's (or a terminal's review)."""
        source = _source('engine.py')
        at = source.index('def on_modifier_gesture(')
        block = source[at:source.index('\n    #: What the walked', at)]
        self.assertIn('with_modifier=False', block)
        self.assertIn('not with_modifier', block)
        hook = _source('keyboard_hook.py')
        self.assertIn('with_modifier=True', hook)

    def test_a_walked_rows_answer_is_said(self):
        """What Enter on a row answers is only RETURNED by the palette."""
        source = _source('engine.py')
        at = source.index('def _walked_key(')
        block = source[at:source.index('\n    def on_walked_numpad', at)]
        self.assertIn('_ok, said = palette.activate()', block)
        self.assertIn('_ok, said = palette.back()', block)


# --------------------------------------------------------------------------- #
# A check box ticked: "checked", a pause, "check box"
# --------------------------------------------------------------------------- #
class ATickedCheckBoxIsHeard(unittest.TestCase):

    def _engine(self):
        from titan_access.engine import TitanAccessEngine
        engine = object.__new__(TitanAccessEngine)
        engine._toggle_known = None
        engine._toggle_said = None
        engine.said = []
        engine.speak_segments = lambda segments, gap_ms=None: \
            engine.said.append((list(segments), gap_ms))
        return engine

    def test_the_state_of_a_box(self):
        from titan_access.engine import TitanAccessEngine as E
        self.assertEqual(E._toggle_state(_Obj('checkbox')), 'unchecked')
        self.assertEqual(E._toggle_state(_Obj('checkbox', states=('checked',))),
                         'checked')
        self.assertEqual(E._toggle_state(
            _Obj('checkbox', states=('partially_checked',))), 'partial')
        self.assertEqual(E._toggle_state(_Obj('radio', states=('selected',))),
                         'selected')
        self.assertEqual(E._toggle_state(_Obj('listitem')), '')

    def test_the_shape_is_state_pause_type(self):
        from titan_access import localization
        localization.set_language('pl')
        engine = self._engine()
        parts = engine.toggle_segments(_Obj('checkbox', name='Widok'),
                                       'checked')
        self.assertEqual([text for text, _pitch in parts],
                         ['zaznaczone', 'Pole wyboru'])
        self.assertEqual(parts[0][1], 4)
        self.assertEqual(parts[1][1], -4)
        parts = engine.toggle_segments(_Obj('checkbox'), 'unchecked')
        self.assertEqual(parts[0][0], 'odznaczone')
        localization.set_language('en')
        parts = engine.toggle_segments(_Obj('checkbox'), 'unchecked')
        self.assertEqual(parts[0][0], 'unchecked')

    def test_it_is_said_with_a_pause_and_once(self):
        engine = self._engine()
        box = _Obj('checkbox', name='A', states=('checked',), hwnd=7)
        engine._announce_toggle(box, 'checked')
        engine._announce_toggle(box, 'checked')
        self.assertEqual(len(engine.said), 1)
        _segments, gap = engine.said[0]
        self.assertGreaterEqual(gap, 200)

    def test_a_state_change_is_only_the_focused_toggles(self):
        engine = self._engine()
        box = _Obj('checkbox', name='A', hwnd=7)
        engine._remember_toggle(box)
        other = _Obj('checkbox', name='B', hwnd=9, states=('checked',))
        engine.on_state_change(other)
        self.assertEqual(engine.said, [])
        ticked = _Obj('checkbox', name='A', hwnd=7, states=('checked',))
        engine.on_state_change(ticked)
        self.assertEqual(len(engine.said), 1)
        # The same state again is not news.
        engine.on_state_change(ticked)
        self.assertEqual(len(engine.said), 1)

    def test_the_second_space_compares_with_what_was_heard(self):
        """The focus snapshot is from before the first Space, so the second
        Space compared the new state with a stale one and said nothing."""
        source = _source('engine.py')
        at = source.index('def _expect_toggle(')
        block = source[at:source.index('\n    def on_state_change', at)]
        self.assertIn('_toggle_known', block)

    def test_the_msaa_hook_hears_a_state_change(self):
        source = _source('msaa_focus.py')
        self.assertIn('EVENT_OBJECT_STATECHANGE = 0x800A', source)
        self.assertIn('def add_state_listener(', source)
        self.assertIn('(EVENT_OBJECT_STATECHANGE,', source)
        manager = _source('provider_manager.py')
        self.assertIn('def add_state_listener(', manager)
        engine = _source('engine.py')
        self.assertIn('p.add_state_listener(self.on_state_change)', engine)
        self.assertIn('self._expect_toggle(self.current_object)', engine)


# --------------------------------------------------------------------------- #
# The reader's settings, walked
# --------------------------------------------------------------------------- #
class TheReadersSettingsAreWalked(unittest.TestCase):

    def setUp(self):
        from titan_access import settings_walk, settings_store
        self.walk = settings_walk
        self.folder = tempfile.mkdtemp()
        self.store = settings_store.SettingsStore(
            os.path.join(self.folder, 'screenReader.ini'))
        self._old_store = settings_walk._store
        settings_walk._store = lambda: self.store
        self.shown = []
        from titan_access.portable import palette
        self._old_show = palette.show
        palette.show = lambda rows, title, back=None, kind='', at=0: (
            self.shown.append((title, rows, at)) or (True, ''))
        settings_walk.forget()

    def tearDown(self):
        from titan_access.portable import palette
        palette.show = self._old_show
        self.walk._store = self._old_store

    def test_every_key_the_settings_page_reads_is_walked(self):
        page = _source('settings_panel.py')
        import re
        read = set(re.findall(r'get_bool\(SEC_\w+, "(\w+)"', page))
        read |= set(re.findall(r'st\.get\(SEC_\w+, "(\w+)"', page))
        read |= set(re.findall(r'get_int\(SEC_\w+, "(\w+)"', page))
        read |= set(re.findall(r'st\.get_bool\("Braille", "(\w+)"', page))
        walked = {entry[1] for _sid, _t, entries in self.walk.SCHEMA
                  for entry in entries if entry[1]}
        missing = sorted(read - walked)
        self.assertEqual(missing, [], 'the page reads %s' % missing)
        for key, _default in __import__(
                'titan_access.settings_panel', fromlist=['SHARED_SWITCHES']
        ).SHARED_SWITCHES:
            self.assertIn(key, walked)

    def test_every_section_is_a_row_and_opens(self):
        ok, _said = self.walk.open_it(None)
        self.assertTrue(ok)
        title, rows, _at = self.shown[-1]
        self.assertEqual(len(rows), len(self.walk.SCHEMA))
        rows[2]['run']()
        title, rows, _at = self.shown[-1]
        self.assertTrue(rows)
        for row in rows:
            self.assertIn(': ', row['label'])

    def test_a_tick_box_flips_in_place_and_is_written(self):
        self.walk.open_section(None, 'verbosity')
        _title, rows, _at = self.shown[-1]
        row = rows[1]
        entry = self.walk.SCHEMA[2][2][1]
        self.assertTrue(self.store.get_bool('Verbosity', entry[1], True))
        ok, said = row['run']()
        self.assertTrue(ok)
        self.assertFalse(self.store.get_bool('Verbosity', entry[1], True))
        self.assertEqual(said, row['label'])
        self.assertTrue(said.endswith(self.walk.L('walk.off')))
        # In place: no new level was put up.
        self.assertEqual(len(self.shown), 1)
        # And it is on disk.
        self.assertIn(entry[1], io.open(self.store.path,
                                        encoding='utf-8').read())

    def test_a_choice_opens_its_answers_with_the_current_one_marked(self):
        self.walk.open_section(None, 'verbosity')
        _title, rows, _at = self.shown[-1]
        rows[-1]['run']()
        title, options, at = self.shown[-1]
        self.assertEqual(len(options), 4)
        self.assertIn(self.walk.L('walk.now'), options[at]['label'])
        options[0]['run']()
        self.assertEqual(self.store.get('Verbosity', 'ToggleKeysMode', ''),
                         'None')
        # Back on the section, on the setting that was answered.
        title, rows, at = self.shown[-1]
        self.assertEqual(at, len(rows) - 1)

    def test_a_label_never_ends_in_two_colons(self):
        for _sid, _title, entries in self.walk.SCHEMA:
            for entry in entries:
                self.assertNotIn('::', self.walk._row_label(entry))


# --------------------------------------------------------------------------- #
# Semantics: the columns of a row, the place the user is in
# --------------------------------------------------------------------------- #
class ARowIsReadWithItsColumns(unittest.TestCase):

    def _row(self):
        table = _Adapted('LIST', 'Files', headers=('Name', 'Type', 'Date'))
        row = _Adapted('LISTITEM', 'readme.txt', parent=table, children=(
            _Adapted('STATICTEXT', 'readme.txt'),
            _Adapted('STATICTEXT', 'Text file'),
            _Adapted('STATICTEXT', 'yesterday')))
        return row

    def test_the_cells_carry_their_headers(self):
        from titan_access import semantics
        self.assertEqual(semantics.cells_of(self._row()),
                         [('Name', 'readme.txt'), ('Type', 'Text file'),
                          ('Date', 'yesterday')])
        self.assertEqual(semantics.cells_of(_Adapted('BUTTON')), [])

    def test_a_module_names_the_kind_column(self):
        from titan_access import semantics

        class Module:
            title_is_a_place = False

            def list_rule(self, obj, application, headers):
                return {'kind_column': 'Type', 'noun': 'file'}

        parts = semantics.row_parts(self._row(), Module(),
                                    name='readme.txt', pitches=(0, -4, 0))
        self.assertEqual(parts, [('Text file', -4), ('Date: yesterday', 0)])

    def test_without_a_module_every_column_after_the_name(self):
        from titan_access import semantics
        parts = semantics.row_parts(self._row(), None, name='readme.txt')
        self.assertEqual([text for text, _p in parts],
                         ['Type: Text file', 'Date: yesterday'])

    def test_the_place_is_said_once_when_it_changes(self):
        from titan_access import semantics
        semantics.forget()

        class Module:
            id = 'tfm'
            title_is_a_place = True

        top = _Adapted('WINDOW', 'C:\\Users')
        row = _Adapted('LISTITEM', 'a', parent=top)
        self.assertEqual(semantics.place_change(row, Module()), 'C:\\Users')
        self.assertEqual(semantics.place_change(row, Module()), '')
        top.name = 'C:\\Users\\Tito'
        self.assertEqual(semantics.place_change(row, Module()),
                         'C:\\Users\\Tito')

        class Elsewhere:
            id = 'tdl'
            title_is_a_place = False
        self.assertEqual(semantics.place_change(row, Elsewhere()), '')

    def test_the_engine_says_both(self):
        source = _source('engine.py')
        self.assertIn('def _semantic_layers(', source)
        self.assertIn('segments = before + segments + after', source)

    def test_an_adapted_object_answers_nvdas_column_api(self):
        source = _source('nvda_shape.py')
        for name in ('def _getColumnHeader(', 'def _getColumnContent(',
                     'def columnCount('):
            self.assertIn(name, source)


# --------------------------------------------------------------------------- #
# A control the program never named
# --------------------------------------------------------------------------- #
class AnUnnamedControlIsNamed(unittest.TestCase):

    def test_the_nearest_caption_inside_left_above(self):
        from titan_access import label_finder as lf
        rect = (100, 100, 200, 120)
        self.assertEqual(lf.nearest(rect, [('Inside', (110, 102, 150, 118))]),
                         'Inside')
        self.assertEqual(lf.nearest(rect, [('Left', (20, 100, 90, 120)),
                                           ('Far', (900, 100, 950, 120))]),
                         'Left')
        self.assertEqual(lf.nearest(rect, [('Above', (100, 70, 160, 90))]),
                         'Above')
        self.assertEqual(lf.nearest(rect, [('Below', (100, 140, 160, 160))]),
                         '')

    def test_the_local_reading_is_kept_per_window(self):
        from titan_access import label_finder as lf
        lf.forget()
        asked = []

        def read(hwnd):
            asked.append(hwnd)
            return [{'text': 'Name:', 'left': 20, 'top': 100, 'width': 60,
                     'height': 20}]

        box = _Obj('edit', bounds=(100, 100, 200, 120), hwnd=5)
        self.assertEqual(lf.from_local_ocr(box, 5, read=read), 'Name:')
        self.assertEqual(lf.from_local_ocr(box, 5, read=read), 'Name:')
        self.assertEqual(asked, [5])
        self.assertEqual(lf.from_local_ocr(_Obj('edit', bounds=(1, 1, 2, 2)),
                                           6, cached_only=True), '')

    def test_the_text_beside_it_through_uia(self):
        from titan_access import label_finder as lf

        class Rect:
            def __init__(self, l, t, r, b):
                self.left, self.top, self.right, self.bottom = l, t, r, b

        class Ctl:
            def __init__(self, kind, name, rect):
                self.ControlTypeName = kind
                self.Name = name
                self.BoundingRectangle = rect

        class Parent:
            def GetChildren(self):
                return [Ctl('TextControl', 'Password:', Rect(20, 100, 90, 120)),
                        Ctl('ButtonControl', 'OK', Rect(20, 200, 90, 220))]

        class Native:
            def GetParentControl(self):
                return Parent()

        box = _Obj('password', bounds=(100, 100, 200, 120), native=Native())
        self.assertEqual(lf.from_uia(box), 'Password')

    def test_the_engine_asks_in_the_cheap_order(self):
        source = _source('engine.py')
        at = source.index('def _label_unnamed(')
        block = source[at:source.index('\n    def _ocr_labels_enabled', at)]
        self.assertLess(block.index('from_uia'), block.index('from_local_ocr'))
        self.assertLess(block.index('from_local_ocr'), block.index('label_for'))
        at = source.index('def _request_ocr_label(')
        block = source[at:source.index('\n    def refresh_current_scope', at)]
        self.assertLess(block.index('from_local_ocr'), block.index('label_for'))
        self.assertIn('label_finder.remember(', block)


# --------------------------------------------------------------------------- #
# NVDA-style application modules
# --------------------------------------------------------------------------- #
class MoreApplicationsHaveAModule(unittest.TestCase):

    def test_the_new_modules_are_registered(self):
        from titan_access.app_modules import manager
        names = {cls.__name__ for cls in manager._MODULE_CLASSES}
        for wanted in ('ShellHostModule', 'LogonModule', 'TaskManagerModule',
                       'ManagementConsoleModule', 'RegistryEditorModule',
                       'SevenZipModule', 'TotalCommanderModule', 'VlcModule',
                       'Foobar2000Module', 'WinampModule',
                       'NotepadPlusPlusModule'):
            self.assertIn(wanted, names)

    def test_every_module_names_its_processes(self):
        from titan_access.app_modules import manager
        seen = {}
        for cls in manager._MODULE_CLASSES:
            names = getattr(cls, 'process_names', None) or {cls.process_name}
            for name in names:
                self.assertTrue(name)
                self.assertEqual(name, name.lower())
                self.assertNotIn(name, seen, '%s and %s both take %s' % (
                    seen.get(name), cls.__name__, name))
                seen[name] = cls.__name__
        for name in ('code', 'discord', 'thunderbird', 'taskmgr', 'lockapp',
                     'searchhost', 'startmenuexperiencehost', 'regedit',
                     'mmc', '7zfm', 'totalcmd', 'vlc', 'notepad++',
                     'mobaxterm'):
            self.assertIn(name, seen, name)

    def test_the_task_switcher_is_not_a_folder(self):
        from titan_access.app_modules.explorer import ExplorerModule
        self.assertFalse(ExplorerModule._is_file_row(
            _Obj('listitem', 'Battle.net', framework_id='XAML',
                 class_name='ListViewItem')))
        self.assertTrue(ExplorerModule._is_file_row(
            _Obj('listitem', 'readme.txt', framework_id='DirectUI')))

    def test_total_commanders_row_is_cells(self):
        from titan_access.app_modules.system_tools import TotalCommanderModule
        self.assertEqual(TotalCommanderModule.split_row('readme\ttxt\t1 024\t2026'),
                         ['readme.txt', '1 024', '2026'])
        self.assertEqual(TotalCommanderModule.split_row('[docs]\t<DIR>\t2026'),
                         ['[docs]', '<DIR>', '2026'])

    def test_a_players_title_is_news_once(self):
        from titan_access.app_modules.media_players import VlcModule
        module = VlcModule(engine=None)
        self.assertEqual(module.clean_title('Song - VLC media player'), 'Song')
        self.assertEqual(module.clean_title('VLC media player'), '')


# --------------------------------------------------------------------------- #
# The reader menu, the shims, the words
# --------------------------------------------------------------------------- #
class TheManagersAreOnTheMenu(unittest.TestCase):

    def test_the_menu_offers_them(self):
        source = _source('reader_menu.py')
        for key in ('readerMenu.settingsWalk', 'readerMenu.readerManager',
                    'readerMenu.speechSchemes', 'readerMenu.classManager',
                    'readerMenu.soundManager', 'readerMenu.virtualWindow',
                    'readerMenu.palette'):
            self.assertIn(key, source)
        self.assertIn('def _after_menu(', source)
        engine = _source('engine.py')
        for action in ('action_speech_schemes', 'action_class_manager',
                       'action_sound_manager', 'action_reader_manager'):
            self.assertIn('def %s(' % action, engine)


class TheSharedModulesFindWhatTheyImport(unittest.TestCase):

    def test_reviews_and_context_are_vendored(self):
        from titan_access.portable import reviews, context, palette
        self.assertTrue(callable(reviews.stop_others))
        self.assertTrue(callable(context.role_name))
        self.assertTrue(callable(palette.show))

    def test_the_two_shims_answer(self):
        from titan_access.portable import elements, configSpec
        self.assertEqual(elements.sequence([('a', 0), ('b', -4)]), ['a, b'])
        self.assertFalse(elements.can_pitch())
        self.assertIn('windowsSemantics', configSpec.read())
        self.assertEqual(elements._states_of(
            _Adapted('CHECKBOX', 'x')), [elements._state_word('UNCHECKED')])

    def test_the_vendor_script_knows_them(self):
        import importlib.util
        path = os.path.join(TITAN, 'src', 'scripts', 'vendor_reader_modules.py')
        spec = importlib.util.spec_from_file_location('vendor', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIn('reviews.py', module.SHARED)
        self.assertIn('context.py', module.SHARED)
        self.assertIn('elements.py', module.SHIMS)
        self.assertIn('configSpec.py', module.SHIMS)

    def test_a_role_in_the_virtual_window_is_a_word(self):
        from titan_access import nvda_shape, localization
        localization.set_language('en')
        self.assertEqual(nvda_shape._Named('MENUBAR').displayString,
                         localization.role_label('menubar'))
        self.assertEqual(nvda_shape._Named('CHECKED').displayString,
                         localization.state_label('checked'))


class TheWordsAreInBothLanguages(unittest.TestCase):

    def test_every_new_key_is_in_both_catalogues(self):
        en = json.load(io.open(os.path.join(COMPONENT, 'locale', 'en.json'),
                               encoding='utf-8'))
        pl = json.load(io.open(os.path.join(COMPONENT, 'locale', 'pl.json'),
                               encoding='utf-8'))
        for key in ('walk.title', 'walk.on', 'walk.off', 'toggle.checked',
                    'toggle.unchecked', 'readerMenu.settingsWalk',
                    'gesture.virtualWindow.name', 'gesture.readerSettings.name',
                    'shell.startMenu', 'logon.lockScreen',
                    'tools.taskManager', 'media.playing',
                    'settings.reader.windowsSemantics'):
            self.assertIn(key, en, key)
            self.assertIn(key, pl, key)
            self.assertNotEqual(en[key], '')
            self.assertNotEqual(pl[key], '')
        self.assertEqual(pl['toggle.checked'], 'zaznaczone')
        self.assertEqual(pl['toggle.unchecked'], 'odznaczone')


if __name__ == '__main__':
    unittest.main(verbosity=1)
