# -*- coding: utf-8 -*-
"""
What Titan does on the way to its window, and what it no longer does there.

Run it directly:  python tests/test_startup.py

Measured before this work, on this machine: `import main` cost **2827 ms**,
building the Settings window (which nobody had asked for) another **2149 ms**,
and `main()` then slept for a flat **two seconds** so the startup sound could
play.  These tests are about the three answers to that - the heavy optional
modules imported when they are used, the Settings window built after Titan's
own is on the screen, and the startup sound's two seconds SPENT rather than
slept - and about the trap each of them sets for whoever changes it next.
"""

import os
import re
import sys
import time
import types
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..')))

from src.lazy_import import LazyModule, lazy_import          # noqa: E402


class LazyImportTests(unittest.TestCase):
    """A name bound now, a module imported when something reads from it."""

    def test_binding_the_name_imports_nothing(self):
        module = lazy_import('src.network.telegram_client')
        self.assertNotIn('telethon', sys.modules,
                         "telethon was imported merely by naming the module")
        self.assertIsInstance(module, types.ModuleType)

    def test_asking_whether_it_is_there_imports_nothing_either(self):
        """The Invisible UI asks this while building its menu, every start."""
        module = lazy_import('src.network.telegram_client')
        self.assertTrue(bool(module))
        self.assertNotIn('telethon', sys.modules)

    def test_reading_from_it_is_what_imports_it(self):
        module = lazy_import('json')
        self.assertEqual(module.dumps({'a': 1}), '{"a": 1}')
        # And it has BECOME the module: no indirection is left.
        self.assertIn('dumps', module.__dict__)

    def test_a_module_that_is_not_there_is_false_like_none_was(self):
        module = lazy_import('titan.no.such.module')
        self.assertFalse(bool(module))
        with self.assertRaises(AttributeError):
            module.anything

    def test_it_does_not_keep_trying_a_module_that_failed(self):
        module = lazy_import('titan.no.such.module')
        with self.assertRaises(AttributeError):
            module.anything
        # The second ask is answered out of what the first one learned.
        self.assertFalse(module.available())

    def test_every_lazy_module_is_in_the_builds_hidden_imports(self):
        """The trap: nothing static points at a lazily imported module.

        PyInstaller finds imports by reading the source, and
        `importlib.import_module(name)` with a name it cannot see is a module
        that will simply not be in the compiled Titan - which fails at the
        moment the user opens Telegram, not at build time.  So every name
        given to `lazy_import` has to be listed in the build, and this is
        what says so.
        """
        wanted = set()
        for folder, _dirs, files in os.walk('src'):
            for name in files:
                if not name.endswith('.py'):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding='utf-8') as handle:
                    source = handle.read()
                wanted.update(re.findall(r"lazy_import\('([^']+)'\)", source))
        wanted.discard('json')
        self.assertTrue(wanted, "no lazily imported modules found at all")
        with open('compiletorelease.py', encoding='utf-8') as handle:
            build = handle.read()
        missing = [name for name in sorted(wanted)
                   if '"%s"' % name not in build and "'%s'" % name not in build]
        self.assertEqual(missing, [], "not in compiletorelease.py's hidden "
                                      "imports: %s" % missing)


class StartupSequenceTests(unittest.TestCase):
    """The order `main()` does things in, and what it no longer waits for."""

    @classmethod
    def setUpClass(cls):
        with open('main.py', encoding='utf-8') as handle:
            cls.source = handle.read()

    def test_the_startup_sound_is_no_longer_slept_through(self):
        """`time.sleep(2)` was two seconds of Titan doing nothing at all."""
        block = self.source[
            self.source.index('sound_thread = threading.Thread'):
            self.source.index('# Dodajemy g')]
        # The speech thread's own `time.sleep(1)` is fine - it is a thread.
        # What must not be here is a sleep on the MAIN thread, which is the
        # one Titan loads on, at this block's own indentation.
        slept = [line for line in block.splitlines()
                 if line.startswith('                time.sleep(')]
        self.assertEqual(slept, [], "the main thread still sleeps through "
                                    "the startup sound")
        self.assertIn('_start_startup_quiet(2.0)', block)
        self.assertIn('_await_startup_quiet', self.source)

    def test_what_is_left_of_it_is_waited_for_just_before_the_window(self):
        showing = self.source.index('# Show the GUI normally')
        waiting = self.source.rindex('_await_startup_quiet', 0, showing)
        between = self.source[waiting:showing]
        self.assertLess(len(between), 400,
                        "the wait is no longer just before the window")

    def test_the_quiet_period_is_spent_not_slept(self):
        """However long loading took comes off the wait."""
        import main
        main._start_startup_quiet(0.3)
        time.sleep(0.35)                      # "loading" took longer than it
        self.assertEqual(main._await_startup_quiet('test'), 0.0)
        main._start_startup_quiet(0.2)
        waited = main._await_startup_quiet('test')
        self.assertGreater(waited, 0.0)
        self.assertLessEqual(waited, 0.2)

    def test_the_settings_window_is_built_after_the_main_one_is_shown(self):
        """2149 ms of a window the user has not asked for."""
        self.assertIn('def build_settings_window', self.source)
        built = self.source.index('wx.CallAfter(build_settings_window)')
        shown = self.source.index('# Show the GUI normally')
        self.assertGreater(built, shown,
                           "the Settings window is still built before the "
                           "main window is on the screen")

    def test_and_before_the_components_that_register_into_it(self):
        built = self.source.index('wx.CallAfter(build_settings_window)')
        components = self.source.index('wx.CallAfter(init_components_delayed)')
        self.assertLess(built, components)

    def test_the_update_check_does_not_pull_requests_at_import_time(self):
        head = self.source[:self.source.index('def check_for_updates_on_startup')]
        self.assertNotIn('from src.system.updater import', head)


class UpdateCheckTests(unittest.TestCase):
    """A server that does not answer must cost a moment, not ten seconds."""

    def test_the_startup_check_has_a_short_timeout(self):
        from src.system import updater
        connect, read = updater.STARTUP_CHECK_TIMEOUT
        self.assertLessEqual(connect, 5)
        self.assertLessEqual(read, 5)

    def test_the_version_probe_uses_it(self):
        from src.system import updater
        with open(updater.__file__, encoding='utf-8') as handle:
            source = handle.read()
        probe = source[source.index('# Get remote version'):]
        probe = probe[:probe.index('response.raise_for_status')]
        self.assertIn('STARTUP_CHECK_TIMEOUT', probe)

    def test_the_download_keeps_its_own_long_one(self):
        """By then there is a window and a progress dialog to wait in."""
        from src.system import updater
        with open(updater.__file__, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('stream=True, timeout=30', source)


class SpeakerTests(unittest.TestCase):
    """`Auto()` walks the whole call stack; nothing may do it at import."""

    def test_nothing_on_the_startup_path_builds_a_speaker_at_import(self):
        for path in ('main.py', 'src/ui/gui.py', 'src/ui/window_switcher.py',
                     'src/ui/notificationcenter.py'):
            with open(path, encoding='utf-8') as handle:
                source = handle.read()
            for line in source.splitlines():
                if line.startswith(('speaker =', '    speaker =',
                                    '        speaker =')):
                    self.assertNotIn('outputs.auto.Auto()', line,
                                     '%s: %s' % (path, line.strip()))

    def test_the_shared_speaker_imports_the_library_when_it_is_needed(self):
        from src.accessibility import lazy_speaker
        with open(lazy_speaker.__file__, encoding='utf-8') as handle:
            source = handle.read()
        head = source[:source.index('def get_shared_speaker')]
        self.assertNotIn('import accessible_output3', head)
        self.assertIn('import accessible_output3',
                      source[source.index('def get_shared_speaker'):])


if __name__ == '__main__':
    unittest.main(verbosity=2)
