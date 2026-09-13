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


if __name__ == '__main__':
    unittest.main(verbosity=2)
