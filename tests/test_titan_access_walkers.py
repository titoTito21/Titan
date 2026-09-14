# -*- coding: utf-8 -*-
"""The ported walkers are USED in Titan Access, not merely carried.

    python tests/test_titan_access_walkers.py

`virtualWindow`, `palette`, `textField` and `titanWalk` are byte-identical
in both readers. In NVDA the plugin borrows the arrows for them; here
nothing did - so the virtual window turned ON in this reader and no key
walked it, which is a feature that reports success and cannot be used.

Nothing here opens a window, speaks or reaches Titan.
"""

import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TITAN = os.path.dirname(HERE)
COMPONENT = os.path.join(TITAN, 'data', 'components', 'titan access')
if COMPONENT not in sys.path:
    sys.path.insert(0, COMPONENT)


def _engine_source():
    return io.open(os.path.join(COMPONENT, 'titan_access', 'engine.py'),
                   encoding='utf-8').read()


class TheKeysReachThem(unittest.TestCase):

    def test_the_walkers_are_asked_before_anything_else(self):
        """They are explicit modes the user turned on, so while one is up
        its keys are its own - the same rule the add-on follows."""
        source = _engine_source()
        at = source.index('def on_plain_key(')
        block = source[at:source.index('\n    def ', at + 10)]
        self.assertIn('_walked_key', block)
        self.assertLess(block.index('_walked_key'), block.index('browse'))

    def test_every_movement_key_is_answered(self):
        source = _engine_source()
        at = source.index('def _walked_key(')
        block = source[at:source.index('\n    def on_plain_key', at)]
        for key in ('up', 'down', 'left', 'right', 'home', 'end',
                    'pageup', 'pagedown', 'escape', 'f5',
                    'numpad7', 'numpad9', 'numpad1', 'numpad3',
                    'numpad4', 'numpad6', 'numpad5'):
            self.assertIn("'%s'" % key, block, 'nothing answers %s' % key)

    def test_the_keys_are_the_nvda_addons_key_for_key(self):
        """Left/Right by layout, Shift the other way, Control by word, the
        corners on Numpad 7/9/1/3 and the layout on 4/6 - in the palette
        AND in the virtual window, since both readers share the modules."""
        source = _engine_source()
        at = source.index('def _walked_key(')
        block = source[at:source.index('\n    def on_walked_numpad', at)]
        for walker in ('palette', 'virtualWindow'):
            for call in ('move_across(', 'move_across_shift(', 'move_word(',
                         'layout_cycle('):
                self.assertIn(walker + '.' + call, block,
                              '%s has no %s' % (walker, call))
        self.assertIn('palette.move_corner(', block)
        self.assertIn('virtualWindow.move_diagonal(', block)
        self.assertIn('virtualWindow.click_mouse(', block)
        # What a layout change answers is only RETURNED by the module, so
        # this reader has to say it itself.
        self.assertGreater(block.count('self._say(str(said))'), 3)

    def test_the_numpad_reaches_a_walker_before_object_navigation(self):
        """With NumLock off Numpad 7 arrives as 'numpad7' and went to the
        object navigator; a walker up at the time never saw its corners."""
        hook = io.open(os.path.join(COMPONENT, 'titan_access',
                                    'keyboard_hook.py'),
                       encoding='utf-8').read()
        self.assertIn('on_walked_numpad', hook)
        self.assertLess(hook.index('on_walked_numpad'),
                        hook.index('numpad nav error'))
        source = _engine_source()
        self.assertIn('def on_walked_numpad(', source)

    def test_the_field_gets_the_letters_and_the_modifiers(self):
        """Or Control and an arrow is a plain arrow and Control and
        Backspace takes one character."""
        source = _engine_source()
        at = source.index('def _walked_key(')
        block = source[at:source.index('\n    def on_plain_key', at)]
        self.assertIn('typing_mode()', block)
        self.assertIn('type_key', block)
        self.assertIn("held.append('ctrl')", block)
        self.assertIn("held.append('shift')", block)

    def test_escape_leaves_the_field_before_the_window(self):
        source = _engine_source()
        at = source.index('def _walked_key(')
        block = source[at:source.index('\n    def on_plain_key', at)]
        typing = block.index('typing_mode()')
        self.assertIn('leave_typing', block[typing:typing + 500])

    def test_nothing_on_the_hook_thread_waits(self):
        """It runs on the keyboard hook, so everything it calls is local:
        moving a cursor in a list already in hand."""
        source = _engine_source()
        at = source.index('def _walked_key(')
        block = source[at:source.index('\n    def on_plain_key', at)]
        for slow in ('time.sleep', 'LINK.bridge', 'requests'):
            self.assertNotIn(slow, block)


class TheSharedModulesAreReachedHere(unittest.TestCase):
    """A module vendored and called by nothing is the silent kind of gap.
    Each of these was one: the busy and attention watcher, the auditory
    icons on the focus path, the kind of a dialog, the touch recogniser,
    the markers, the reader's own switches on the settings page."""

    def test_the_engine_starts_and_stops_the_shared_watchers(self):
        source = _engine_source()
        self.assertIn('states.start()', source)
        self.assertIn("for name in ('states', 'monitors', 'agentLink'):", source)
        self.assertIn('readerApi.hooks = nvda_shape.Hooks(self)', source)
        self.assertIn('touchRecognizer.listener = self._on_touch', source)
        self.assertIn('monitors.start()', source)
        self.assertIn('self._start_live_watch()', source)

    def test_the_focus_path_plays_an_icon_and_says_the_dialogs_kind(self):
        source = _engine_source()
        at = source.index('def announce_object(')
        block = source[at:source.index('\n    def ', at + 10)]
        self.assertIn('self._auditory_icon(obj)', block)
        self.assertIn('self._dialog_kind_of(obj)', block)
        self.assertIn('icons.for_focus(obj)', source)
        self.assertIn('dialog_kind.kind_of_window(obj.hwnd)', source)

    def test_a_gesture_goes_to_a_walked_list_first_and_the_screen_second(self):
        source = _engine_source()
        at = source.index('def _on_touch(')
        block = source[at:source.index('\n    def ', at + 10)]
        self.assertIn('touchWalk.handle(action, x, y)', block)
        self.assertIn('self._object_at_point(x, y)', block)
        self.assertIn('self.provider.object_from_point(int(x), int(y))', source)

    def test_markers_and_the_manager_have_keys(self):
        source = _engine_source()
        for name in ('"markHere"', '"goToMarker"', '"readerManager"'):
            self.assertIn(name, source)
        for handler in ('action_mark_here', 'action_go_to_marker',
                        'action_reader_manager'):
            self.assertIn('def %s(' % handler, source)

    def test_the_settings_page_shows_the_shared_switches(self):
        page = io.open(os.path.join(COMPONENT, 'titan_access',
                                    'settings_panel.py'),
                       encoding='utf-8').read()
        for key in ('auditoryIcons', 'soundScheme', 'dialogKinds',
                    'busyState', 'attentionState'):
            self.assertIn('"%s"' % key, page)
        import json
        for lang in ('en', 'pl'):
            words = json.load(io.open(os.path.join(
                COMPONENT, 'locale', '%s.json' % lang), encoding='utf-8'))
            self.assertIn('settings.section.reader', words)
            self.assertIn('settings.reader.soundScheme', words)

    def test_the_state_words_go_through_the_sound_scheme(self):
        page = io.open(os.path.join(COMPONENT, 'titan_access',
                                    'accessible.py'), encoding='utf-8').read()
        self.assertIn('schemes.answer(', page)
        self.assertIn('_through_the_sound_scheme(', page)


class TitanAccessObjectsWearNvdasShape(unittest.TestCase):
    """One adapter gives a Titan Access object the attribute names the
    shared modules read, so a marker keyed by automation id here is the
    same marker under NVDA, and a reader module matches the same window."""

    def _adapt(self, **fields):
        import sys
        sys.path.insert(0, COMPONENT)
        from titan_access import nvda_shape
        base = dict(name='Save', role='button', value='', description='',
                    states={'unavailable', 'haspopup'}, class_name='Button',
                    automation_id='btnSave', hwnd=0, process_id=0,
                    bounds=(1, 2, 3, 4), native=None)
        base.update(fields)
        return nvda_shape.adapt(type('O', (), base)())

    def test_roles_states_and_identity_come_out_in_nvdas_spelling(self):
        a = self._adapt()
        self.assertEqual(a.role.name, 'BUTTON')
        self.assertEqual({s.name for s in a.states}, {'UNAVAILABLE', 'HASPOPUP'})
        self.assertEqual(a.windowClassName, 'Button')
        self.assertEqual(a.UIAAutomationId, 'btnSave')
        self.assertEqual(tuple(a.location), (1, 2, 3, 4))
        self.assertEqual(self._adapt(role='listitem').role.name, 'LISTITEM')
        self.assertEqual(self._adapt(role='menu').role.name, 'POPUPMENU')

    def test_a_marker_made_here_has_a_strong_key(self):
        import sys
        sys.path.insert(0, COMPONENT)
        from titan_access.portable import anchors, labels
        a = self._adapt()
        key, strong = labels.key_of(a)
        self.assertTrue(strong)
        self.assertEqual(anchors.anchor_for(a)['kind'], anchors.BY_CONTROL)

    def test_the_hooks_spell_keys_for_the_keyboard_library(self):
        import sys
        sys.path.insert(0, COMPONENT)
        from titan_access import nvda_shape
        spell = nvda_shape.Hooks._key_name
        self.assertEqual(spell('control+shift+s'), 'ctrl+shift+s')
        self.assertEqual(spell('upArrow'), 'up')
        self.assertEqual(spell('enter'), 'enter')

    def test_the_engine_records_runs_and_watches(self):
        source = _engine_source()
        for name in ('"recordProcedure"', '"runProcedure"', '"watchControl"'):
            self.assertIn(name, source)
        self.assertIn('markers.mark(adapted)', source)
        self.assertIn('markers.go(marker)', source)
        self.assertIn('procedures.run(procedure', source)
        self.assertIn('monitors.watch_this_control(adapted)', source)
        self.assertIn('guest.consider(adapted)', source)
        self.assertIn('surface.consider(adapted', source)
        self.assertIn('readerModules.for_object(adapted)', source)
        self.assertIn('live.changed(child)', source)


class TheReaderHasCategoriesAVoiceAndAPageAsAWindow(unittest.TestCase):
    """The settings are a category with categories inside it; the reader
    may have a voice of its own; a web page is a virtual window of its
    lines; and the IA2 proxy is looked for and registered per process."""

    def _settings_frame_helpers(self):
        import io as _io
        source = _io.open(os.path.join(COMPONENT, '..', '..', '..', 'src', 'ui',
                                       'settingsgui.py'), encoding='utf-8').read()
        return source

    def test_the_settings_window_nests_a_category_under_its_parent(self):
        source = self._settings_frame_helpers()
        self.assertIn('def register_category(self, name, panel, save_callback=None, load_callback=None,\n                          parent=None)', source)
        self.assertIn('self.category_parents', source)
        # The two helpers, exercised on a stand-in: order and display.
        import types, sys
        sys.path.insert(0, os.path.join(COMPONENT, '..', '..', '..'))
        from src.ui import settingsgui
        fake = types.SimpleNamespace(category_order=['A', 'Titan Access', 'Z'],
                                     category_parents={})
        settingsgui.SettingsFrame._insert_under(fake, 'Titan Access: Speech', 'Titan Access')
        fake.category_parents['Titan Access: Speech'] = 'Titan Access'
        settingsgui.SettingsFrame._insert_under(fake, 'Titan Access: Dial', 'Titan Access')
        fake.category_parents['Titan Access: Dial'] = 'Titan Access'
        self.assertEqual(fake.category_order,
                         ['A', 'Titan Access', 'Titan Access: Speech',
                          'Titan Access: Dial', 'Z'])
        self.assertEqual(settingsgui.SettingsFrame._display_name(fake, 'Titan Access: Dial'),
                         '    Dial')
        self.assertEqual(settingsgui.SettingsFrame._display_name(fake, 'A'), 'A')

    def test_every_section_builds_loads_and_saves_on_its_own_panel(self):
        try:
            import wx
        except ImportError:
            self.skipTest('no wx')
        import sys
        sys.path.insert(0, COMPONENT)
        from titan_access import settings_panel, settings_store
        app = wx.App.Get() or wx.App(False)
        frame = wx.Frame(None)
        import tempfile
        store = settings_store.SettingsStore(
            os.path.join(tempfile.mkdtemp(), 'reader.ini'))
        real = settings_panel.get_settings
        settings_panel.get_settings = lambda: store
        settings_panel._apply_live = lambda st: None
        try:
            for which in ('main',) + settings_panel.SECTIONS:
                panel = settings_panel.build_panel(frame, which)
                settings_panel.load_panel(panel)
                settings_panel.save_panel(panel)
                panel.Destroy()
        finally:
            settings_panel.get_settings = real
            frame.Destroy()

    def test_the_reader_registers_a_category_per_section(self):
        page = io.open(os.path.join(COMPONENT, 'titan_access', 'settings_panel.py'),
                       encoding='utf-8').read()
        self.assertIn("parent=main)", page)
        self.assertIn("for which in SECTIONS:", page)

    def test_the_own_voice_is_a_private_engine(self):
        source = io.open(os.path.join(COMPONENT, 'titan_access', 'speech_adapter.py'),
                         encoding='utf-8').read()
        self.assertIn('get_private_reader_engine()', source)
        self.assertIn('"OwnVoice"', source)
        self.assertEqual(source.count('def apply_settings('), 1)
        speech = io.open(os.path.join(COMPONENT, '..', '..', '..', 'src', 'titan_core',
                                      'tce_speech.py'), encoding='utf-8').read()
        self.assertIn('def get_private_reader_engine(', speech)

    def test_a_page_is_a_virtual_window_of_its_lines(self):
        source = _engine_source()
        self.assertIn('virtualWindow.document_rows = self._document_rows', source)
        self.assertIn('def _document_rows(', source)
        self.assertIn('vbuf.build_for_window(hwnd, allow_ocr=False)', source)

    def test_the_ia2_proxy_is_looked_for(self):
        import sys
        sys.path.insert(0, COMPONENT)
        from titan_access import ia2
        self.assertIsInstance(ia2.proxy_registered(), bool)
        self.assertIsInstance(ia2.proxy_candidates(), list)
        self.assertIn('IAccessible2', ia2.IA2_INTERFACES)
        self.assertIn('ia2.ensure_proxy()', _engine_source())


class TheyCanBeOpenedAtAll(unittest.TestCase):
    """A mode nothing can turn on is a mode nobody has."""

    def test_each_has_a_gesture(self):
        source = _engine_source()
        for name in ('virtualWindow', 'commandPalette', 'titanWindow',
                     'trackpad'):
            self.assertIn('g.register("%s"' % name, source,
                          '%s cannot be turned on' % name)

    def test_each_gesture_names_a_handler_that_exists(self):
        import ast
        source = _engine_source()
        tree = ast.parse(source)
        defined = {node.name for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for wanted in ('action_toggle_virtual_window', 'action_command_palette',
                       'action_titan_window', 'action_toggle_trackpad'):
            self.assertIn(wanted, defined)

    def test_a_command_this_reader_has_not_got_says_so(self):
        """Rather than pretending: the add-on's `commands` module opens
        NVDA dialogs and reads NVDA's own objects."""
        source = _engine_source()
        at = source.index('def _palette_run(')
        block = source[at:source.index('\n    def action_titan_window', at)]
        self.assertIn('not in this reader', block)


class TheyAreTheSameFile(unittest.TestCase):
    """Byte-identical, or the two readers disagree."""

    def test_the_walkers_are_vendored(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'vendor', os.path.join(TITAN, 'src', 'scripts',
                                   'vendor_reader_modules.py'))
        vendor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vendor)
        listed = {name[:-3] for name in vendor.SHARED}
        for wanted in ('virtualWindow', 'palette', 'textField', 'titanWalk',
                       'sceneModel', 'iconNames', 'dialog_kind'):
            self.assertIn(wanted, listed, '%s is not shared' % wanted)

    def test_they_really_import_here(self):
        for name in ('virtualWindow', 'palette', 'textField', 'titanWalk'):
            __import__('titan_access.portable.%s' % name)


class TheFifthPassReachesTheRest(unittest.TestCase):
    """The last of the 'still missing' list: the rate a voice class
    carries, the smart OCR cursor's keys, a picture said as what it is,
    a proxy DLL of this repository's own, and the Java Access Bridge."""

    def test_a_voice_class_rate_travels_with_the_part(self):
        from titan_access import accessible
        from titan_access.portable import classes
        saved = classes.voice_of
        try:
            classes.voice_of = lambda tag: {'pitch': 0, 'rate': 3, 'volume': 0}
            part = accessible._part('3 of 10', 'place', 0)
        finally:
            classes.voice_of = saved
        self.assertEqual(len(part), 5)
        self.assertEqual(part[3], 3)
        classes_source = io.open(os.path.join(
            TITAN, 'src', 'titan_core', 'stereo_speech.py'),
            encoding='utf-8').read()
        at = classes_source.index('def speak_concat(')
        block = classes_source[at:classes_source.index('\n    def ', at + 10)]
        self.assertIn('self.set_rate(max(-10, min(10, base_rate + rate)))',
                      block)
        self.assertIn('self.set_rate(base_rate)', block)

    def test_the_engine_remembers_the_rate_it_was_set_to(self):
        sys.path.insert(0, TITAN)
        try:
            from src.titan_core import stereo_speech
        finally:
            sys.path.remove(TITAN)
        engine = stereo_speech.StereoSpeech.__new__(stereo_speech.StereoSpeech)
        engine.engine = 'none'
        engine.sapi = None
        engine.set_rate(4)
        self.assertEqual(engine._rate_setting, 4)
        engine.set_rate(40)
        self.assertEqual(engine._rate_setting, 10)

    def test_the_smart_cursor_and_the_picture_kinds_are_vendored_and_wired(self):
        for name in ('smart', 'graphics'):
            self.assertTrue(os.path.isfile(os.path.join(
                COMPONENT, 'titan_access', 'portable', name + '.py')), name)
        source = _engine_source()
        at = source.index('def _walked_key(')
        block = source[at:source.index('\n    def ', at + 10)]
        for call in ('smart.active()', 'smart.move(1)', 'smart.move(-1)',
                     'smart.press()', 'smart.forget()'):
            self.assertIn(call, block)
        at = source.index('def announce_object(')
        block = source[at:source.index('\n    def ', at + 10)]
        self.assertIn('graphics.parts(adapted)', block)
        self.assertIn("obj.role == 'image'", block)

    def test_the_smart_cursors_announcement_is_spoken_here(self):
        from titan_access.portable import compat
        from titan_access import speech_adapter
        heard = []
        saved = speech_adapter.speak
        try:
            speech_adapter.speak = lambda text, *a, **k: heard.append(text)
            self.assertTrue(compat.speech.speak(['Save', object(), 'button']))
            self.assertFalse(compat.speech.speak([]))
        finally:
            speech_adapter.speak = saved
        self.assertEqual(heard, ['Save, button'])

    def test_the_proxy_of_our_own_is_built_and_tried_first(self):
        from titan_access import ia2
        self.assertTrue(os.path.isfile(ia2.OWN_PROXY), ia2.OWN_PROXY)
        self.assertEqual(ia2.PROXY_FILES[0][0], os.path.dirname(ia2.OWN_PROXY))
        self.assertTrue(os.path.isfile(os.path.join(
            COMPONENT, 'helper', 'ia2proxy', 'build.bat')))

    def test_the_java_bridge_answers_nothing_without_a_java(self):
        from titan_access import jab
        self.assertFalse(jab.available())
        self.assertFalse(jab.is_java_window(0))
        self.assertIsNone(jab.focus(0))
        self.assertEqual(jab.nodes(0), [])
        self.assertIsInstance(jab._candidates(), list)
        self.assertEqual(jab.ROLES['push button'], 'button')
        self.assertEqual(jab.ROLES['page tab'], 'tab')

    def test_a_java_accessible_becomes_a_titan_access_object(self):
        from titan_access import jab

        class Info(object):
            name = 'Save'
            description = 'Saves the file'
            role_en_US = 'push button'
            states_en_US = 'enabled,focusable,focused'
            x, y, width, height = 10, 20, 100, 30
            indexInParent = 2
            childrenCount = 0
            accessibleText = False

        class Context(object):
            def info(self):
                return Info()

        obj = jab.describe(Context())
        self.assertEqual(obj.role, 'button')
        self.assertEqual(obj.name, 'Save')
        self.assertIn('focused', obj.states)
        self.assertNotIn('unavailable', obj.states)
        self.assertEqual(obj.bounds, (10, 20, 100, 30))
        self.assertEqual(obj.pos_in_set, 3)
        self.assertEqual(obj.provider, 'jab')
        Info.states_en_US = 'checked,focusable'
        self.assertIn('unavailable', jab.states_of(Info()))
        self.assertIn('checked', jab.states_of(Info()))

    def test_a_java_window_is_asked_first_by_the_virtual_buffer(self):
        from titan_access import virtual_buffer
        source = io.open(os.path.join(COMPONENT, 'titan_access',
                                      'virtual_buffer.py'),
                         encoding='utf-8').read()
        self.assertIn('tiers = ["jab", "uia", "msaa", "win32", "drawn"]',
                      source)
        self.assertEqual(virtual_buffer._build_tier('jab', 0, None, None), [])
        engine = _engine_source()
        self.assertIn('java = self._java_focus(obj)', engine)
        self.assertIn('jab.start()', engine)


class TheSpeechSchemesAndTheArrowsAreThisReadersToo(unittest.TestCase):
    """The scheme a user made under either reader is the scheme under the
    other, and a walked list here closes when its window is left."""

    def setUp(self):
        import tempfile
        import shutil
        from titan_access.portable import speechSchemes
        self.schemes = speechSchemes
        folder = tempfile.mkdtemp(prefix='titan-test-')
        self.addCleanup(shutil.rmtree, folder, True)
        self._folder = speechSchemes._folder
        speechSchemes._folder = lambda: folder
        speechSchemes.forget()
        self.addCleanup(speechSchemes.forget)
        self.addCleanup(setattr, speechSchemes, '_folder', self._folder)

    def test_describe_goes_through_the_scheme(self):
        from titan_access import accessible
        from titan_access.contracts import AccessibleObject

        class Settings:
            def get_bool(self, *_a):
                return True

            def get(self, *_a, **_k):
                return None
        obj = AccessibleObject(name='Save', role='button', states={'pressed'})
        self.schemes.use('terse')
        said = [text for text, *_rest in accessible.describe(obj, Settings())]
        self.assertEqual(said[0], 'Save')
        self.assertNotIn(accessible.role_label('button'), said)
        self.schemes.use('classic')
        said = [text for text, *_rest in accessible.describe(obj, Settings())]
        self.assertEqual(said[:2], ['Save', accessible.role_label('button')])
        key = self.schemes.create('Mine')
        self.schemes.set_rule(key, 'button', kind_word='przycisk!')
        self.schemes.use(key)
        said = [text for text, *_rest in accessible.describe(obj, Settings())]
        self.assertIn('przycisk!', said)

    def test_the_engine_plays_the_schemes_sound_switches_and_follows_focus(self):
        source = _engine_source()
        self.assertIn('speechSchemes.sounded(speechSchemes.kind_of(obj.role))',
                      source)
        self.assertIn('g.register("speechScheme", "shift+s", '
                      'self.action_speech_scheme)', source)
        self.assertIn('self._walkers_follow_the_focus()', source)
        at = source.index('def _walkers_follow_the_focus(')
        block = source[at:source.index('\n    def ', at + 10)]
        for name in ('virtualWindow', 'ocrReview', 'palette'):
            self.assertIn("'%s'" % name, block)
        self.assertIn('smart.forget()', block)
        self.assertIn('smart.active() and smart.window() == '
                      'self._foreground_hwnd()', source)
        for name in ('speechSchemes', 'schemeWalk'):
            self.assertTrue(os.path.isfile(os.path.join(
                COMPONENT, 'titan_access', 'portable', name + '.py')), name)


class BrailleShowsAControlInCells(unittest.TestCase):
    """The last of the gap list: a control in braille, translated with
    liblouis, shaped by the speech scheme's braille rule, sent to a
    display through BrlAPI or shown in a viewer."""

    def setUp(self):
        import tempfile
        import shutil
        from titan_access import braille
        from titan_access.portable import speechSchemes
        self.braille = braille
        self.schemes = speechSchemes
        folder = tempfile.mkdtemp(prefix='titan-test-')
        self.addCleanup(shutil.rmtree, folder, True)
        self._folder = speechSchemes._folder
        speechSchemes._folder = lambda: folder
        speechSchemes.forget()
        self.addCleanup(speechSchemes.forget)
        self.addCleanup(setattr, speechSchemes, '_folder', self._folder)

    def test_liblouis_translates_and_the_cells_are_real(self):
        if not self.braille.available():
            self.skipTest("no liblouis on this machine")
        cells = self.braille.translate('Save')
        self.assertTrue(cells)
        self.assertTrue(all(0x2800 <= ord(c) <= 0x28FF for c in cells))
        self.assertEqual(len(self.braille.cells_of(cells)), len(cells))
        # Untranslatable-free text still comes back, never empty.
        self.assertEqual(self.braille.translate(''), '')
        self.assertTrue(self.braille.translate('X'))

    def test_the_line_follows_the_schemes_braille_rule(self):
        from titan_access.contracts import AccessibleObject
        obj = AccessibleObject(name='Save', role='button', states={'focused'})
        key = self.schemes.create('t')
        self.schemes.set_rule(key, 'button',
                              braille={'kind': 'btn', 'parts': ['name', 'kind']})
        self.schemes.use(key)
        self.assertEqual(self.braille.line_for(obj), 'Save btn')
        self.schemes.set_rule(key, 'button',
                              braille={'kind': '', 'parts': ['name', 'kind']})
        self.assertEqual(self.braille.line_for(obj), 'Save')

    def test_show_is_off_by_default_and_says_the_line_when_on(self):
        import tempfile
        import shutil
        from titan_access.contracts import AccessibleObject
        from titan_access import settings_store
        folder = tempfile.mkdtemp(prefix='titan-test-')
        self.addCleanup(shutil.rmtree, folder, True)
        store = settings_store.get_settings()
        obj = AccessibleObject(name='Save', role='button')
        store.set_bool('Braille', 'Enabled', False)
        store.set_bool('Braille', 'Viewer', False)
        self.assertEqual(self.braille.show_object(obj), '')
        store.set_bool('Braille', 'Enabled', True)
        from titan_access import accessible
        expected = ('Save ' + accessible.role_label('button')).strip()
        self.assertEqual(self.braille.show_object(obj), expected)
        store.set_bool('Braille', 'Enabled', False)

    def test_the_engine_and_the_buffer_reach_braille(self):
        source = _engine_source()
        at = source.index('def announce_object(')
        block = source[at:source.index('\n    def ', at + 10)]
        self.assertIn('braille.show_object(obj)', block)
        buffer = io.open(os.path.join(COMPONENT, 'titan_access',
                                      'virtual_buffer.py'),
                         encoding='utf-8').read()
        self.assertIn('"drawn"', buffer)
        self.assertIn('def build_drawn(', buffer)
        self.assertIn('tiers = ["jab", "uia", "msaa", "win32", "drawn"]',
                      buffer)
        self.assertIn('"drawn": _activate_drawn', buffer)

    def test_the_braille_section_is_a_reader_section(self):
        from titan_access import settings_panel
        self.assertIn('braille', settings_panel.SECTIONS)
        self.assertIn('braille', settings_panel._BUILDERS)
        import json
        for lang in ('en', 'pl'):
            words = json.load(io.open(os.path.join(
                COMPONENT, 'locale', '%s.json' % lang), encoding='utf-8'))
            self.assertIn('settings.section.braille', words)
            self.assertIn('settings.braille.enabled', words)


if __name__ == '__main__':
    unittest.main(verbosity=2)
