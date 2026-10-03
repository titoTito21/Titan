# -*- coding: utf-8 -*-
"""Every setting of Titan Access, described once and read somewhere.

`settings_schema` is the one table the settings page, the walked settings,
the store's defaults, the per-program profiles and the settings ring are
built from. These tests hold the table to its promises: every entry has a
label and a help sentence in both languages, every key is READ by the
engine (a switch that changes nothing cannot be added), the store's
defaults know every key, a profile lays its answers over the store and
`General/Enabled` never, the ring moves and changes, the symbol rules say
what they claim, and the page builds every section out of the table.

Run directly: ``python tests/test_titan_access_settings.py``.
"""

import io
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
for path in (COMPONENT, TITAN):
    if path not in sys.path:
        sys.path.insert(0, path)

from titan_access import settings_schema as schema          # noqa: E402
from titan_access import settings_store, settings_walk       # noqa: E402

_WX_APP = []


def _wx_app():
    import wx
    app = wx.GetApp()
    if app is None:
        app = wx.App(False)
        _WX_APP.append(app)
    return app


def _locale(lang):
    return json.load(io.open(os.path.join(COMPONENT, 'locale', lang + '.json'),
                             encoding='utf-8'))


def _engine_sources():
    """Every module that may READ a setting: the package without the three
    that describe, show or walk them."""
    skip = {'settings_schema.py', 'settings_panel.py', 'settings_walk.py',
            'settings_store.py', 'settings_ring.py'}
    found = {}
    for root, _dirs, files in os.walk(os.path.join(COMPONENT, 'titan_access')):
        for name in files:
            if name.endswith('.py') and name not in skip:
                path = os.path.join(root, name)
                found[path] = io.open(path, encoding='utf-8').read()
    return found


class _FakeEngine:
    def __init__(self, store):
        self.settings = store
        self.said = []
        self.speech = None

    def speak(self, text, *a, **k):
        self.said.append(str(text))

    def play(self, *a, **k):
        pass

    def apply_settings(self, reason=''):
        self.applied = reason


class TheSchemaIsTheOneDescription(unittest.TestCase):

    def test_every_entry_has_its_words_in_both_languages(self):
        for lang in ('pl', 'en'):
            words = _locale(lang)
            for sid, title, _rows in schema.SECTIONS:
                self.assertIn(title, words, (lang, sid))
            for entry in schema.entries():
                self.assertIn(entry.label, words, (lang, entry))
                self.assertIn(entry.help, words, (lang, entry))
                for _value, key in schema.options(entry) if entry.kind == 'choice' else ():
                    self.assertIn(key, words, (lang, entry.key, key))

    def test_the_polish_help_has_polish_letters_where_it_should(self):
        words = _locale('pl')
        helped = [words[e.help] for e in schema.entries()]
        self.assertTrue(any(re.search('[ąćęłńóśźż]', one) for one in helped))
        for sentence in helped:
            self.assertTrue(sentence.endswith('.'), sentence)

    def test_every_key_is_read_by_the_engine(self):
        """A setting nothing reads does not exist."""
        sources = _engine_sources()
        joined = '\n'.join(sources.values())
        # A typed property of the store (`settings.mute_outside_tce`) is a
        # read of its key wherever the property's name is used.
        store_source = io.open(os.path.join(COMPONENT, 'titan_access',
                                            'settings_store.py'),
                               encoding='utf-8').read()
        by_property = {}
        for prop, key in re.findall(
                r'def (\w+)\(self\):\s*(?:v = |return )?[\w.]*\(?self\.get\w*\('
                r'(?:SEC_\w+|"\w+"), "(\w+)"', store_source):
            by_property.setdefault(key, set()).add(prop)
        unread = []
        for entry in schema.entries():
            if entry.kind == 'scheme':
                continue
            if '"%s"' % entry.key in joined or "'%s'" % entry.key in joined:
                continue
            if any('.%s' % prop in joined for prop in by_property.get(entry.key, ())):
                continue
            # The shared switches are read by name through the switchboard.
            if entry.section == 'Reader' and entry.key[0].islower() and \
                    ("'%s'" % entry.key in joined or '"%s"' % entry.key in joined):
                continue
            unread.append((entry.section, entry.key))
        self.assertEqual(unread, [])

    def test_the_store_knows_every_default(self):
        for entry in schema.entries():
            if entry.kind == 'scheme':
                continue
            self.assertIn((entry.section, entry.key), settings_store.DEFAULTS, entry)
            self.assertEqual(settings_store.DEFAULTS[(entry.section, entry.key)],
                             schema.encode(entry, entry.default))

    def test_the_walk_is_the_schema(self):
        self.assertEqual(settings_walk.SCHEMA, schema.as_walk_schema())
        self.assertEqual([sid for sid, _t, _r in settings_walk.SCHEMA],
                         [sid for sid, _t, _r in schema.SECTIONS])

    def test_the_ring_names_real_entries(self):
        for section, key in schema.RING:
            self.assertIsNotNone(schema.find(section, key), (section, key))

    def test_the_new_sections_are_there(self):
        ids = [sid for sid, _t, _r in schema.SECTIONS]
        for wanted in ('keyboard', 'symbols', 'browse', 'mouse'):
            self.assertIn(wanted, ids)
        self.assertEqual(ids.index('general'), 1)


class TheSymbolRules(unittest.TestCase):

    def test_punctuation_levels(self):
        from titan_access import symbols
        text = 'a, b; c_d'
        self.assertEqual(symbols.process_text(text, 'none'), 'a, b; c_d')
        self.assertIn('przecinek', symbols.process_text(text, 'some').lower()
                      + symbols.process_text(text, 'some'))
        self.assertNotIn('rednik', symbols.process_text(text, 'some'))
        self.assertIn('rednik', symbols.process_text(text, 'most'))
        self.assertNotIn('podkre', symbols.process_text(text, 'most'))
        self.assertIn('podkre', symbols.process_text(text, 'all'))

    def test_numbers(self):
        from titan_access import symbols
        self.assertEqual(symbols.digits('tel 123456', 'digits'), 'tel 1 2 3 4 5 6')
        self.assertEqual(symbols.digits('tel 12345', 'pairs'), 'tel 12 34 5')
        self.assertEqual(symbols.digits('tel 12345', 'whole'), 'tel 12345')
        self.assertEqual(symbols.digits('a 7 b', 'digits'), 'a 7 b')

    def test_a_capital_as_the_setting_says(self):
        from titan_access import symbols
        store = settings_store.SettingsStore(
            os.path.join(tempfile.mkdtemp(), 'r.ini'))
        for mode, want in (('pitch', ('a', 3, False)), ('beep', ('a', 0, True)),
                           ('none', ('a', 0, False))):
            store.set('Symbols', 'CapitalLetters', mode)
            self.assertEqual(symbols.describe_char('A', store), want, mode)
        store.set('Symbols', 'CapitalLetters', 'word')
        said, pitch, beep = symbols.describe_char('A', store)
        self.assertIn('a', said)
        self.assertNotEqual(said, 'a')
        store.set('Symbols', 'CapitalPitchOffset', '7')
        store.set('Symbols', 'CapitalLetters', 'pitch')
        self.assertEqual(symbols.describe_char('Z', store)[1], 7)
        self.assertEqual(symbols.describe_char('.', store)[0], symbols.name_of('.'))

    def test_the_indent(self):
        from titan_access import symbols
        self.assertEqual(symbols.trim_leading('    x'), ('x', 4))


class ProfilesLayOverTheStore(unittest.TestCase):

    def setUp(self):
        from titan_access import profiles
        self.profiles = profiles
        self.folder = tempfile.mkdtemp()
        self._old_folder = profiles.folder
        profiles.folder = lambda: self.folder
        profiles.forget()
        self.store = settings_store.SettingsStore(
            os.path.join(tempfile.mkdtemp(), 'r.ini'))

    def tearDown(self):
        self.profiles.forget()
        self.profiles.folder = self._old_folder

    def test_an_override_is_written_read_and_laid_over(self):
        p = self.profiles
        self.assertTrue(p.override('notepad', 'Symbols', 'PunctuationLevel', 'all'))
        self.assertEqual(p.get('notepad', 'Symbols', 'PunctuationLevel'), 'all')
        self.assertEqual(p.programs(), ['notepad'])
        self.assertEqual(self.store.get('Symbols', 'PunctuationLevel'), 'some')
        self.assertTrue(p.activate('notepad'))
        self.assertEqual(self.store.get('Symbols', 'PunctuationLevel'), 'all')
        self.assertTrue(p.activate(''))
        self.assertEqual(self.store.get('Symbols', 'PunctuationLevel'), 'some')

    def test_the_switch_is_never_in_a_profile(self):
        p = self.profiles
        self.assertFalse(p.override('notepad', 'General', 'Enabled', 'true'))
        self.assertIsNone(p.get('notepad', 'General', 'Enabled'))

    def test_following_the_focus_activates_only_a_program_with_a_profile(self):
        p = self.profiles
        p.override('notepad', 'Mouse', 'TrackMouse', 'true')
        engine = _FakeEngine(self.store)
        p.program_of = lambda obj: str(obj)
        self.assertTrue(p.follow('notepad', engine, pid=11))
        self.assertEqual(p.active(), 'notepad')
        self.assertEqual(engine.applied, 'profile')
        self.assertTrue(self.store.get_bool('Mouse', 'TrackMouse', False))
        self.assertTrue(p.follow('calc', engine, pid=12))
        self.assertEqual(p.active(), '')
        self.assertFalse(self.store.get_bool('Mouse', 'TrackMouse', False))
        # The same pid again names the program from memory.
        p.program_of = lambda obj: 'wrong'
        p.follow('notepad', engine, pid=11)
        self.assertEqual(p.active(), 'notepad')

    def test_removing_a_profile_puts_the_store_back(self):
        p = self.profiles
        p.override('notepad', 'Mouse', 'TrackMouse', 'true')
        p.activate('notepad')
        self.assertTrue(p.remove('notepad'))
        self.assertEqual(p.programs(), [])
        self.assertEqual(p.active(), '')
        self.assertFalse(self.store.get_bool('Mouse', 'TrackMouse', False))

    def test_the_walk_writes_into_the_profile_being_edited(self):
        p = self.profiles
        old_store = settings_walk._store
        settings_walk._store = lambda: self.store
        from titan_access.portable import palette
        old_show = palette.show
        palette.show = lambda rows, title, back=None, kind='', at=0: (True, '')
        try:
            settings_walk.open_it(None, program='notepad')
            entry = ('Symbols', 'NumbersAs', 'settings.symbols.numbersAs',
                     'choice', None, 'whole')
            settings_walk.set_value(entry, 'digits', None)
            self.assertEqual(p.get('notepad', 'Symbols', 'NumbersAs'), 'digits')
            self.assertEqual(self.store.get('Symbols', 'NumbersAs'), 'whole')
            self.assertEqual(settings_walk.value_of(entry), 'digits')
            label = settings_walk._row_label(entry)
            self.assertIn('(', label)
            settings_walk.open_it(None)
            self.assertEqual(settings_walk.value_of(entry), 'whole')
        finally:
            settings_walk._store = old_store
            palette.show = old_show


class TheRing(unittest.TestCase):

    def setUp(self):
        self.store = settings_store.SettingsStore(
            os.path.join(tempfile.mkdtemp(), 'r.ini'))
        self._old_store = settings_walk._store
        settings_walk._store = lambda: self.store
        self._old_switch = settings_walk._switch_reader
        settings_walk._switch_reader = lambda on: None

    def tearDown(self):
        settings_walk._store = self._old_store
        settings_walk._switch_reader = self._old_switch

    def test_it_moves_and_changes(self):
        from titan_access.settings_ring import SettingsRing
        engine = _FakeEngine(self.store)
        ring = SettingsRing(engine)
        self.assertTrue(ring.say_current())
        self.assertIn(':', engine.said[-1])
        ring.at = 0                                    # Speech/Rate
        self.assertTrue(ring.change(1))
        self.assertEqual(self.store.get_int('Speech', 'Rate', 0), 1)
        self.assertTrue(ring.change(-1))
        self.assertEqual(self.store.get_int('Speech', 'Rate', 0), 0)
        ring.at = len(ring.entries()) - 1              # Mouse/TrackMouse
        ring.change(1)
        self.assertTrue(self.store.get_bool('Mouse', 'TrackMouse', False))
        ring.move(1)
        self.assertEqual(ring.at, 0)

    def test_zero_is_a_value_not_unset(self):
        entry = ('Speech', 'Pitch', 'settings.speech.pitch', 'range', (-10, 10, 1), 0)
        self.assertEqual(settings_walk.value_word(entry, 0), '0')
        self.assertEqual(settings_walk.value_word(entry, -3), '-3')

    def test_the_punctuation_level_steps_and_stops_at_the_edge(self):
        from titan_access.settings_ring import SettingsRing
        engine = _FakeEngine(self.store)
        ring = SettingsRing(engine)
        entries = ring.entries()
        ring.at = [e[1] for e in entries].index('PunctuationLevel')
        ring.change(1)
        self.assertEqual(self.store.get('Symbols', 'PunctuationLevel'), 'most')
        ring.change(1)
        self.assertEqual(self.store.get('Symbols', 'PunctuationLevel'), 'all')
        ring.change(1)
        self.assertEqual(self.store.get('Symbols', 'PunctuationLevel'), 'all')


class TheMouseAndTheBrowseSettingsAreRead(unittest.TestCase):

    def test_the_tracker_reads_its_switch(self):
        from titan_access.mouse_tracker import MouseTracker
        store = settings_store.SettingsStore(
            os.path.join(tempfile.mkdtemp(), 'r.ini'))
        tracker = MouseTracker(_FakeEngine(store))
        self.assertFalse(tracker.wanted())
        store.set_bool('Mouse', 'TrackMouse', True)
        self.assertTrue(tracker.wanted())
        self.assertIsNone(MouseTracker.text_at(object(), 0, 0, 'word'))
        self.assertFalse(tracker.running)

    def test_the_walk_tells_the_whole_reader_not_only_its_voice(self):
        """Insert+Ctrl+G, "track the mouse: on" - and the tracker never
        started, because `_apply` told the speech alone. The walk asks
        `engine.apply_settings`, which starts and stops the tracker."""
        from titan_access import settings_walk as walk
        from titan_access.mouse_tracker import MouseTracker
        store = settings_store.SettingsStore(
            os.path.join(tempfile.mkdtemp(), 'r.ini'))
        engine = _FakeEngine(store)
        engine.speech = None
        engine.mouse = MouseTracker(engine)
        applied = []

        def apply_settings(reason=''):
            applied.append(reason)
            if engine.mouse.wanted() and not engine.mouse.running:
                engine.mouse.start()
            elif not engine.mouse.wanted() and engine.mouse.running:
                engine.mouse.stop()
        engine.apply_settings = apply_settings
        had = walk._store
        walk._store = lambda: store
        try:
            entry = [r for _s, _t, rows in schema.as_walk_schema() for r in rows
                     if r[:2] == ('Mouse', 'TrackMouse')][0]
            walk.set_value(entry, True, engine)
            self.assertTrue(engine.mouse.running)
            walk.set_value(entry, False, engine)
            self.assertFalse(engine.mouse.running)
        finally:
            walk._store = had
            engine.mouse.stop()
        self.assertTrue(applied and applied[0].startswith('walk:'))

    def test_the_buffer_says_a_role_only_when_wanted(self):
        from titan_access.browse_mode import BrowseModeHandler
        store = settings_store.SettingsStore(
            os.path.join(tempfile.mkdtemp(), 'r.ini'))
        handler = BrowseModeHandler.__new__(BrowseModeHandler)
        handler.engine = _FakeEngine(store)
        self.assertTrue(handler._report_wanted('link'))
        store.set_bool('Browse', 'ReportLinks', False)
        self.assertFalse(handler._report_wanted('link'))
        self.assertTrue(handler._report_wanted('button'))
        self.assertEqual(handler._browse_setting('SayAllRate', 0), 0)

    def test_the_hook_asks_for_command_keys_only_when_told(self):
        from titan_access.keyboard_hook import KeyboardHook
        store = settings_store.SettingsStore(
            os.path.join(tempfile.mkdtemp(), 'r.ini'))
        engine = _FakeEngine(store)
        engine.on_command_key = lambda label: engine.said.append('cmd:' + label)
        engine.on_modifier_key = lambda name: engine.said.append('mod:' + name)
        hook = KeyboardHook(engine)
        hook._command_pressed('control+s')
        hook._modifier_pressed('shift')
        self.assertEqual(engine.said, [])
        store.set_bool('Keyboard', 'SpeakCommandKeys', True)
        store.set_bool('Keyboard', 'SpeakModifierKeys', True)
        hook._command_pressed('control+s')
        hook._modifier_pressed('shift')
        self.assertEqual(engine.said, ['cmd:control+s', 'mod:shift'])


class ThePageIsBuiltFromTheSchema(unittest.TestCase):

    def test_every_section_builds_every_entry(self):
        try:
            import wx
        except Exception:                            # noqa: BLE001
            self.skipTest('no wx')
        _wx_app()
        from titan_access import settings_panel
        frame = wx.Frame(None)
        try:
            for sid, _title, rows in schema.SECTIONS:
                if sid == 'speech':
                    continue
                panel = settings_panel.build_panel(frame, sid)
                for entry in rows:
                    self.assertIn((entry.section, entry.key), panel.controls,
                                  (sid, entry.key))
                    _e, ctrl = panel.controls[(entry.section, entry.key)]
                    if (entry.section, entry.key) != ('General', 'Enabled'):
                        self.assertTrue(ctrl.GetToolTipText(), entry.key)
                panel.Destroy()
        finally:
            frame.Destroy()


if __name__ == '__main__':
    unittest.main(verbosity=1)
