"""The parts of Titan that had no Linux or macOS half now have one.

Measured under WSLg on 2026-09-30: Titan starts on a Debian 11 with
wxPython 4.2.1 on GTK 3, speaks through its own eSpeak NG library and
through speech-dispatcher, and its main window - menu bar, tab buttons and
the application list with "Aplikacje, 1 z 6" - is read whole through
AT-SPI, which is what Orca reads. These tests pin the pieces that made
that true and that a Windows machine can still check.

Run directly: ``python tests/test_posix_platform.py``.
"""
import importlib.util
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TheSystemToolsExistOnEveryPlatform(unittest.TestCase):

    def test_the_posix_table_names_the_same_tools_as_windows(self):
        from src.ai.tools import system_tools, system_tools_posix
        from src.ai.agent_tools import _tool
        S, N, B = {'type': 'string'}, {'type': 'number'}, {'type': 'boolean'}
        windows = [t['name'] for t in system_tools._tool_table(system_tools, _tool, S, N, B)]
        posix = [t['name'] for t in system_tools._tool_table(system_tools_posix, _tool, S, N, B)]
        self.assertEqual(windows, posix)
        self.assertEqual(len(posix), 17)

    def test_every_posix_tool_answers_a_sentence_when_its_command_is_missing(self):
        from src.ai.tools import system_tools_posix as posix
        saved = posix._has
        posix._has = lambda tool: False
        try:
            for fn, args in ((posix.system_get_volume, {}), (posix.system_set_volume, {'percent': 50}),
                             (posix.system_set_mute, {}), (posix.system_list_audio_devices, {}),
                             (posix.system_set_audio_device, {'name': 'x'}),
                             (posix.system_get_power_plan, {}), (posix.system_list_power_plans, {}),
                             (posix.system_set_power_plan, {'name': 'balanced'}),
                             (posix.system_set_theme, {'mode': 'dark'}),
                             (posix.system_list_wifi, {}), (posix.system_connect_wifi, {'name': 'x'}),
                             (posix.system_open_settings_page, {'page': 'sound'})):
                answer = fn(**args)
                self.assertIsInstance(answer, str, fn.__name__)
                self.assertTrue(answer.strip(), fn.__name__)
        finally:
            posix._has = saved

    def test_a_bad_number_is_refused_in_words(self):
        from src.ai.tools import system_tools_posix as posix
        self.assertIn('0 to 100', posix.system_set_volume('loud'))
        self.assertIn('0 to 100', posix.system_set_brightness(None))


class TheDesktopToolsNeverRaiseOffWindows(unittest.TestCase):

    def test_missing_tools_are_named_not_raised(self):
        from src.ai import desktop_tools_posix as desktop
        saved = desktop.shutil.which
        desktop.shutil.which = lambda tool: None
        saved_atspi = desktop._atspi
        desktop._atspi = lambda: None
        try:
            for fn, args in ((desktop.get_foreground_window, {}), (desktop.list_windows, {}),
                             (desktop.focus_window, {'title': 'x'}), (desktop.read_focused_window, {})):
                answer = fn(**args)
                self.assertIsInstance(answer, str, fn.__name__)
            path, reason = desktop.screenshot_png_path()
            if sys.platform != 'darwin':
                self.assertIsNone(path)
                self.assertTrue(reason)
        finally:
            desktop.shutil.which = saved
            desktop._atspi = saved_atspi


class AnEngineSaysWhichPlatformsItRunsOn(unittest.TestCase):

    def test_the_manifest_key(self):
        from src.tts.engine_registry import _engine_runs_here
        self.assertTrue(_engine_runs_here(''))
        self.assertTrue(_engine_runs_here(None))
        here = {'win32': 'windows', 'darwin': 'macos'}.get(sys.platform, 'linux')
        self.assertTrue(_engine_runs_here(here))
        self.assertTrue(_engine_runs_here('windows, linux, macos'))
        other = 'linux' if here != 'linux' else 'windows'
        self.assertFalse(_engine_runs_here(other))

    def test_the_windows_binary_engines_say_so(self):
        import configparser
        for folder in ('bestspeech', 'DECTalk', 'eloquence', 'milena', 'SMP', 'supertonic', 'festival'):
            parser = configparser.ConfigParser()
            parser.read(os.path.join(ROOT, 'data', 'titantts engines', folder, '__engine__.TCE'),
                        encoding='utf-8')
            self.assertEqual(parser.get('engine', 'platforms', fallback=''), 'windows', folder)


class AForeignCompiledFileIsNotLoaded(unittest.TestCase):

    def test_the_magic_number_is_checked(self):
        from src.titan_core.component_manager import ComponentManager
        with tempfile.TemporaryDirectory() as folder:
            foreign = os.path.join(folder, 'init.pyc')
            with open(foreign, 'wb') as f:
                # Any magic but this interpreter's (b'+\x0e\r\n' IS 3.14's).
                f.write(b'\x00\x00\r\n' + b'\0' * 12)
            self.assertFalse(ComponentManager._pyc_is_ours(foreign))
            ours = os.path.join(folder, 'ours.pyc')
            with open(ours, 'wb') as f:
                f.write(importlib.util.MAGIC_NUMBER + b'\0' * 12)
            self.assertTrue(ComponentManager._pyc_is_ours(ours))


class TheEventLoopIsMadeWhereItIsNeeded(unittest.TestCase):

    def test_ensure_event_loop_answers_a_loop_twice(self):
        from src.titan_core.asyncio_compat import ensure_event_loop
        first = ensure_event_loop()
        second = ensure_event_loop()
        self.assertIs(first, second)
        self.assertFalse(first.is_closed())


if __name__ == '__main__':
    unittest.main(verbosity=2)
