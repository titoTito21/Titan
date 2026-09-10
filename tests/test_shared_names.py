# -*- coding: utf-8 -*-
"""What the user teaches one reader, known to the other.

Run it directly (`python tests/test_shared_names.py`).

The two halves are written in different trees by different code - the NVDA
add-on's `shared.py` and Titan Access's `shared_names.py` - and the one
thing that makes them one feature is that they agree, exactly, on where the
file is and how a control is spelled in it. Agreeing ALMOST is two stores
that happen to share a file, which is the failure this file exists to
prevent.

Nothing here touches the user's own shared file: everything runs in a
folder of its own.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ADDON = os.path.join(ROOT, 'nvda-addon', 'addon', 'globalPlugins')
ACCESS = os.path.join(ROOT, 'data', 'components', 'titan access')
for where in (ADDON, ACCESS):
    if where not in sys.path:
        sys.path.insert(0, where)

if 'globalPluginHandler' not in sys.modules:
    _stub = types.ModuleType('globalPluginHandler')

    class _GlobalPlugin:
        def __init__(self):
            pass

        def terminate(self):
            pass
    _stub.GlobalPlugin = _GlobalPlugin
    sys.modules['globalPluginHandler'] = _stub

from titanEnhancements import labels                          # noqa: E402
from titanEnhancements import shared as addon_side            # noqa: E402
from titan_access import shared_names as titan_side           # noqa: E402


def _control(name='saveButton', klass='SomeApp', role='BUTTON',
             application='someapp'):
    return types.SimpleNamespace(
        windowHandle=0, windowClassName=klass, UIAAutomationId=name, name='',
        role=types.SimpleNamespace(name=role),
        appModule=types.SimpleNamespace(appName=application))


class OneSourceInTwoTrees(unittest.TestCase):
    """What the add-on has, Titan Access has - and it is the SAME file.

    Vendored rather than imported because the two ship separately: the
    add-on is a `.nvda-addon` a user installs into NVDA, Titan Access is a
    Titan component, and neither may depend on the other being on the
    machine. Vendoring is only honest if it is checked, which is this.
    """

    def _vendor(self):
        sys.path.insert(0, os.path.join(ROOT, 'src', 'scripts'))
        try:
            import vendor_reader_modules
            return vendor_reader_modules
        finally:
            sys.path.pop(0)

    def test_they_have_not_drifted_apart(self):
        vendor = self._vendor()
        same, wrong = vendor.check()
        self.assertTrue(same, '; '.join(wrong))

    def test_the_shared_list_is_not_empty(self):
        """A vendoring script that copies nothing passes every check."""
        vendor = self._vendor()
        self.assertGreaterEqual(len(vendor.SHARED), 5)

    #: Everything shared, by the name it has in both trees.
    PORTABLE = ('anchors', 'classes', 'findControl', 'labels', 'layers',
                'monitors', 'perProgram', 'procedures', 'schemes', 'shared',
                'toolkit', 'verify', 'virtualInput', 'windowKind',
                'windowsAndActions')

    def test_every_shared_module_really_imports_in_titan_access(self):
        """Byte-identical is worth nothing if it will not load there."""
        import importlib
        for name in self.PORTABLE:
            module = importlib.import_module(
                'titan_access.portable.%s' % name)
            self.assertTrue(module, name)

    def test_the_vendor_list_and_the_package_say_the_same_thing(self):
        """A module vendored and not imported is one nobody can reach;
        one imported and not vendored is one that will go stale."""
        vendor = self._vendor()
        listed = {name[:-3] for name in vendor.SHARED}
        self.assertEqual(listed, set(self.PORTABLE))
        from titan_access import portable
        self.assertEqual(set(portable.__all__), set(self.PORTABLE))

    def test_each_of_them_keeps_its_store_in_TITANS_folder(self):
        """Not NVDA's. The same file answers both, and inside Titan
        Access it has to answer Titan's."""
        import importlib
        for name in ('labels', 'classes', 'schemes', 'procedures',
                     'monitors', 'perProgram'):
            module = importlib.import_module(
                'titan_access.portable.%s' % name)
            where = module.path()
            self.assertTrue(where, name)
            self.assertIn('titosoft', where.lower(), name)
            self.assertNotIn(os.path.join('roaming', 'nvda').lower(),
                             where.lower(), name)

    def test_they_really_answer_and_not_just_import(self):
        """A module that imports and answers nothing is the failure this
        whole exercise is about."""
        from titan_access.portable import (classes, layers, toolkit,
                                           windowKind, virtualInput)
        self.assertGreater(len(classes.labels()), 10)
        self.assertTrue(layers.names())
        self.assertTrue(layers.help_for(layers.names()[0]))
        self.assertEqual(toolkit.word('qt'), 'Qt')
        self.assertTrue(windowKind.word('application'))
        reading = types.SimpleNamespace(lines=[[
            {'text': 'File', 'left': 10, 'top': 10, 'width': 40,
             'height': 16}]])
        self.assertEqual([node.text for node in virtualInput.build(reading)],
                         ['File'])

    def test_the_shim_answers_where_NVDA_would_have(self):
        """The one thing that differs between the trees."""
        from titan_access.portable import i18n
        namespace = {}
        translate = i18n.install(namespace)
        self.assertTrue(callable(translate))
        self.assertIn('_', namespace)
        # A missing translation is never a missing string.
        self.assertEqual(translate('Never translated anywhere'),
                         'Never translated anywhere')

    def test_they_work_with_no_nvda_under_them(self):
        """Titan Access has none, and each of them was made to answer
        honestly rather than to be forked to fit."""
        from titan_access.portable import windowKind, toolkit, virtualInput
        self.assertIsNone(windowKind._control_types())
        self.assertFalse(windowKind.is_unknown_word('button'))
        self.assertTrue(windowKind.word('application'))
        self.assertEqual(toolkit.of(None), ('', '', ''))
        self.assertEqual(virtualInput.build(None), [])

    def test_the_shared_store_is_the_same_store_from_both(self):
        """The point of the whole exercise."""
        from titan_access.portable import labels as theirs
        from titanEnhancements import labels as mine
        obj = _control()
        self.assertEqual(mine.key_of(obj), theirs.key_of(obj))
        self.assertEqual(os.path.basename(mine.FILENAME),
                         os.path.basename(theirs.FILENAME))


class TheTwoHalvesAgree(unittest.TestCase):
    """The whole feature is that they do, exactly."""

    def test_they_look_in_the_same_folder(self):
        self.assertEqual(addon_side.folder(), titan_side.folder())

    def test_they_spell_a_control_the_same_way(self):
        """A key spelled almost the same is two stores sharing a file."""
        obj = _control()
        mine, _strong = labels.key_of(obj)
        theirs = titan_side.key_of('SomeApp', 'BUTTON',
                                   automation_id='saveButton')
        self.assertEqual(mine, theirs)
        self.assertTrue(mine)

    def test_they_agree_on_a_control_with_no_automation_id(self):
        """The weak key, which is the one with a rule in it."""
        obj = _control(name='')
        obj.indexInParent = 4
        mine, strong = labels.key_of(obj)
        self.assertFalse(strong)
        theirs = titan_side.key_of('SomeApp', 'BUTTON', index_in_parent=4)
        self.assertEqual(mine, theirs)

    def test_a_control_with_nothing_stable_has_no_key_either_side(self):
        obj = _control(name='', klass='')
        obj.indexInParent = -1
        obj.role = types.SimpleNamespace(name='')
        mine, _strong = labels.key_of(obj)
        self.assertEqual(mine, '')
        self.assertEqual(titan_side.key_of('', '', index_in_parent=-1), '')

    def test_the_file_is_the_same_file(self):
        self.assertEqual(os.path.basename(addon_side.path('labels')),
                         titan_side.FILENAME)


class WhatIsWrittenIsWhatIsRead(unittest.TestCase):
    """End to end, in a folder of its own."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='titanshared_')
        self.addCleanup(shutil.rmtree, self.folder, True)
        shared = os.path.join(self.folder, 'shared')
        os.makedirs(shared, exist_ok=True)
        for module in (addon_side, titan_side):
            was = module.folder
            module.folder = lambda where=shared: where
            self.addCleanup(setattr, module, 'folder', was)
        titan_side.forget()
        self.addCleanup(titan_side.forget)

    def _write(self, rows):
        with open(os.path.join(self.folder, 'shared', titan_side.FILENAME),
                  'w', encoding='utf-8') as handle:
            json.dump(rows, handle)
        titan_side.forget()

    def test_a_name_written_by_one_is_read_by_the_other(self):
        obj = _control()
        key, _strong = labels.key_of(obj)
        self._write({'someapp': {key: {'label': 'Save', 'source': 'user',
                                       'at': 100}}})
        self.assertEqual(titan_side.name_for('someapp', key), 'Save')

    def test_a_remembered_description_crosses_too(self):
        """A reading is a REQUEST; paying for it twice because the user
        changed readers is the thing this stops."""
        obj = _control()
        key, _strong = labels.key_of(obj)
        self._write({'someapp': {key: {'label': 'Save',
                                       'description': 'A floppy disk.'}}})
        self.assertEqual(titan_side.description_for('someapp', key),
                         'A floppy disk.')

    def test_what_the_user_decided_crosses_too(self):
        obj = _control()
        key, _strong = labels.key_of(obj)
        self._write({'someapp': {key: {'silent': True, 'role_word': 'toolbar',
                                       'note': 'read only'}}})
        found = titan_side.custom_for('someapp', key)
        self.assertTrue(found.get('silent'))
        self.assertEqual(found.get('role_word'), 'toolbar')
        self.assertEqual(found.get('note'), 'read only')

    def test_nothing_stored_is_an_empty_answer_not_a_failure(self):
        self.assertEqual(titan_side.name_for('someapp', 'nothing|like|this'),
                         '')
        self.assertEqual(titan_side.custom_for('someapp', ''), {})

    def test_a_half_written_file_is_answered_with_nothing(self):
        """The other reader writes it beside and moves it into place, so
        this should never happen - and a reader must not stop if it does."""
        with open(os.path.join(self.folder, 'shared', titan_side.FILENAME),
                  'w', encoding='utf-8') as handle:
            handle.write('{"someapp": {"a": ')
        titan_side.forget()
        self.assertEqual(titan_side.name_for('someapp', 'a'), '')

    def test_the_notes_row_is_not_mistaken_for_a_control(self):
        """`__notes__` is the program's own bucket, not a control of it."""
        self._write({'someapp': {'__notes__': {'window_icon': 'a leaf'}}})
        self.assertEqual(titan_side.name_for('someapp', '__notes__'), '')


class MergingIsNotChoosing(unittest.TestCase):
    """A machine where one reader has not run for a month must not lose
    what the other learned."""

    def test_a_typed_name_beats_a_newer_guess(self):
        mine = {'app': {'k': {'label': 'Mine', 'source': 'user', 'at': 100}}}
        theirs = {'app': {'k': {'label': 'Theirs', 'source': 'ai',
                                'at': 999}}}
        merged, _taken, _given, _conflicts = addon_side.merge(mine, theirs)
        self.assertEqual(merged['app']['k']['label'], 'Mine')

    def test_otherwise_the_newest_wins(self):
        mine = {'app': {'k': {'label': 'Old', 'source': 'ai', 'at': 1}}}
        theirs = {'app': {'k': {'label': 'New', 'source': 'ai', 'at': 2}}}
        merged, _t, _g, _c = addon_side.merge(mine, theirs)
        self.assertEqual(merged['app']['k']['label'], 'New')

    def test_a_row_only_one_side_has_is_kept(self):
        mine = {'app': {'a': {'label': 'A'}}}
        theirs = {'other': {'b': {'label': 'B'}}}
        merged, _t, _g, _c = addon_side.merge(mine, theirs)
        self.assertEqual(merged['app']['a']['label'], 'A')
        self.assertEqual(merged['other']['b']['label'], 'B')

    def test_merging_nothing_with_nothing_is_nothing(self):
        merged, _t, _g, _c = addon_side.merge({}, {})
        self.assertEqual(merged, {})
        merged, _t, _g, _c = addon_side.merge(None, None)
        self.assertEqual(merged, {})

    def test_rubbish_on_one_side_does_not_lose_the_other(self):
        mine = {'app': {'a': {'label': 'A'}}}
        merged, _t, _g, _c = addon_side.merge(mine, {'app': 'not a dict'})
        self.assertEqual(merged['app']['a']['label'], 'A')

    def test_it_says_which_way_each_row_went(self):
        """So a person can be told what really happened."""
        row, whose = addon_side.better({'at': 1}, {'at': 2})
        self.assertEqual((row['at'], whose), (2, 'theirs'))
        row, whose = addon_side.better({'at': 3}, {'at': 2})
        self.assertEqual((row['at'], whose), (3, 'mine'))
        row, whose = addon_side.better(None, {'at': 2})
        self.assertEqual(whose, 'theirs')
        row, whose = addon_side.better({'at': 2}, None)
        self.assertEqual(whose, 'mine')

    def test_bringing_it_in_does_not_replace_what_the_user_typed_here(self):
        store = {'someapp': {'k': {'label': 'Typed here',
                                   'source': 'user', 'at': 1}}}
        was_load, was_save = labels._load, labels.save
        labels._load = lambda: store
        labels.save = lambda: True
        try:
            brought = labels.take_shared(
                {'someapp': {'k': {'label': 'Guessed there',
                                   'source': 'ai', 'at': 999}}})
        finally:
            labels._load, labels.save = was_load, was_save
        self.assertEqual(brought, 0)
        self.assertEqual(store['someapp']['k']['label'], 'Typed here')

    def test_bringing_in_something_new_really_brings_it(self):
        store = {}
        was_load, was_save = labels._load, labels.save
        labels._load = lambda: store
        labels.save = lambda: True
        try:
            brought = labels.take_shared(
                {'someapp': {'k': {'label': 'From the other reader',
                                   'source': 'user', 'at': 1}}})
        finally:
            labels._load, labels.save = was_load, was_save
        self.assertEqual(brought, 1)
        self.assertEqual(store['someapp']['k']['label'],
                         'From the other reader')


class TitanAccessREALLYUsesIt(unittest.TestCase):
    """A package that is present and wired to nothing is the failure this
    repository keeps finding. So: named in NVDA, read by Titan Access."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='titanboth_')
        self.addCleanup(shutil.rmtree, self.folder, True)
        shared = os.path.join(self.folder, 'shared')
        os.makedirs(shared, exist_ok=True)
        from titan_access import shared_names
        self.shared_names = shared_names
        for module in (addon_side, shared_names):
            was = module.folder
            module.folder = lambda where=shared: where
            self.addCleanup(setattr, module, 'folder', was)
        shared_names.forget()
        self.addCleanup(shared_names.forget)
        self.store = {}
        was_load, was_save = labels._load, labels.save
        labels._load = lambda: self.store
        labels.save = lambda: True
        self.addCleanup(setattr, labels, '_load', was_load)
        self.addCleanup(setattr, labels, 'save', was_save)

    def _theirs(self):
        return types.SimpleNamespace(
            class_name='SomeApp', role='BUTTON', automation_id='btn1',
            control_id=0, pos_in_set=0, process_id=0, app_name='someapp')

    def _name_it(self, **custom):
        obj = _control(name='btn1')
        labels.put(obj, 'Send message', source='user')
        if custom:
            labels.customise(obj, **custom)
        ok, _said = addon_side.sync_labels()
        self.assertTrue(ok)
        self.shared_names.forget()

    def test_a_name_given_in_nvda_is_read_by_titan_access(self):
        from titan_access import accessible
        self._name_it()
        self.assertEqual(accessible._shared_name_for(self._theirs()),
                         'Send message')

    def test_the_key_titan_access_builds_is_the_addons_own(self):
        from titan_access import accessible
        program, key = accessible._shared_key(self._theirs())
        mine, _strong = labels.key_of(_control(name='btn1'))
        self.assertEqual(key, mine)
        self.assertEqual(program, 'someapp')

    def test_what_the_user_decided_reaches_the_reading(self):
        from titan_access import accessible
        self._name_it(role_word='toolbar', note='read only')
        found = accessible._custom_for(self._theirs())
        self.assertEqual(found.get('role_word'), 'toolbar')
        self.assertEqual(found.get('note'), 'read only')

    def test_a_silent_control_is_read_as_nothing_at_all(self):
        """Asked FIRST, so a control somebody switched off is never
        described and then thrown away."""
        from titan_access import accessible
        source = io.open(os.path.join(ACCESS, 'titan_access',
                                      'accessible.py'), encoding='utf-8').read()
        at = source.index('def describe(')
        block = source[at:at + 2500]
        self.assertIn('custom.get("silent")', block)
        self.assertLess(block.index('custom.get("silent")'),
                        block.index('want_name'),
                        'it is described before it is thrown away')

    def test_the_reading_path_really_calls_it(self):
        """Wired to something, not merely present."""
        source = io.open(os.path.join(ACCESS, 'titan_access',
                                      'accessible.py'), encoding='utf-8').read()
        for call in ('_custom_for(obj)', '_shared_name_for(obj)',
                     'custom.get("role_word")', 'custom.get("note")'):
            self.assertIn(call, source, call)


class ItIsNeverOnTheFocusPath(unittest.TestCase):
    """Milliseconds on every control is a reader that got slower for no
    reason anybody can see."""

    def test_titan_access_reads_the_file_once_and_keeps_it(self):
        import io
        with io.open(os.path.join(ACCESS, 'titan_access', 'shared_names.py'),
                     encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('STAT_INTERVAL', source)
        self.assertIn('_stamp', source)

    def test_the_addon_syncs_off_the_focus_path(self):
        import io
        with io.open(os.path.join(ADDON, 'titanEnhancements', '__init__.py'),
                     encoding='utf-8') as handle:
            source = handle.read()
        at = source.index('shared.sync_labels()')
        before = source[max(0, at - 3000):at]
        # It happens in the watcher that notices Titan connecting - a
        # thread of the add-on's own - and not in an event handler.
        self.assertIn('def _watch(self)', before)
        self.assertIn('self._watching.wait(', before)
        for event in ('def event_gainFocus', 'def event_foreground',
                      'def event_nameChange'):
            self.assertNotIn(event, before,
                             'the sync sits inside %s' % event)


if __name__ == '__main__':
    unittest.main(verbosity=2)
