"""Titan Access, the shell and the Windows-binary engines off Windows.

Measured in WSLg on 2026-09-30: Titan Access read a wx window in another
process through AT-SPI and spoke "Zapisz / Przycisk", "Zaznacz mnie / Pole
wyboru / niezaznaczono"; the shell put up its taskbar, desktop and Start
menu, and AT-SPI listed "Start (push button) | Otwarte okna (panel) |
Zasobnik systemowy (panel) | Pokaż pulpit (push button)"; DECtalk,
Eloquence, SMP and Festival synthesised through Wine (1.6 to 2.5 seconds
of audio each). These tests pin what a Windows machine can still check.

Run directly: ``python tests/test_linux_reader_and_shell.py``.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
TA = os.path.join(ROOT, 'data', 'components', 'titan access')
if TA not in sys.path:
    sys.path.insert(0, TA)


class TheKeyboardArrivesAsVirtualKeys(unittest.TestCase):

    def test_x_keysyms_become_the_keys_the_hook_knows(self):
        from titan_access import atspi_keys as k
        self.assertEqual(k.vk_of(0xff63), (0x2D, True))     # Insert
        self.assertEqual(k.vk_of(0xff9e), (0x2D, False))    # KP_Insert
        self.assertEqual(k.vk_of(0xffe5), (0x14, False))    # Caps_Lock
        self.assertEqual(k.vk_of(0x61), (ord('A'), False))  # a
        self.assertEqual(k.vk_of(0x41), (ord('A'), False))  # A
        self.assertEqual(k.vk_of(0x31), (ord('1'), False))
        self.assertEqual(k.vk_of(0x21), (ord('1'), False))  # ! is the 1 key
        self.assertEqual(k.vk_of(0xffbe), (0x70, False))    # F1
        self.assertEqual(k.vk_of(0xffc9), (0x7B, False))    # F12
        self.assertEqual(k.vk_of(0xff54), (0x28, True))     # Down
        self.assertEqual(k.vk_of(0xffea), (0xA5, True))     # Alt_R (AltGr)
        self.assertEqual(k.vk_of(0x1000105), (ord('A'), False))  # ą as a Unicode keysym
        self.assertEqual(k.vk_of(0xffff00), (0, False))     # nothing


class TheWindowsBridgesRunUnderWine(unittest.TestCase):

    def test_the_command_and_the_path_off_windows(self):
        from src.tts import native_bridge as nb
        saved = (nb.IS_WINDOWS, nb._wine, nb._looked)
        try:
            nb.IS_WINDOWS = False
            nb._wine, nb._looked = '/usr/bin/wine', True
            self.assertEqual(nb.bridge_command('/x/bridge.exe', '-v'), ['/usr/bin/wine', '/x/bridge.exe', '-v'])
            self.assertTrue(nb.host_path('/tmp/a b.txt').startswith('Z:'))
            self.assertNotIn('/', nb.host_path('/tmp/a.txt'))
            self.assertIn('WINEPREFIX', nb.popen_kwargs()['env'])
            nb._wine, nb._looked = None, True
            self.assertFalse(nb.bridge_available(__file__))
            self.assertIn('wine', nb.why_unavailable(__file__))
            with self.assertRaises(FileNotFoundError):
                nb.bridge_command('/x/bridge.exe')
        finally:
            nb.IS_WINDOWS, nb._wine, nb._looked = saved

    def test_on_windows_the_exe_runs_as_itself(self):
        from src.tts import native_bridge as nb
        saved = nb.IS_WINDOWS
        try:
            nb.IS_WINDOWS = True
            self.assertEqual(nb.bridge_command('C:/b.exe'), ['C:/b.exe'])
            self.assertEqual(nb.host_path('C:/a.txt'), 'C:/a.txt')
            self.assertIn('creationflags', nb.popen_kwargs())
        finally:
            nb.IS_WINDOWS = saved

    def test_the_bridge_engines_say_they_run_off_windows_too(self):
        import configparser
        for folder in ('DECTalk', 'eloquence', 'SMP', 'festival'):
            parser = configparser.ConfigParser()
            parser.read(os.path.join(ROOT, 'data', 'titantts engines', folder, '__engine__.TCE'),
                        encoding='utf-8')
            self.assertIn('linux', parser.get('engine', 'platforms'), folder)
        parser = configparser.ConfigParser()
        parser.read(os.path.join(ROOT, 'data', 'titantts engines', 'milena', '__engine__.TCE'), encoding='utf-8')
        self.assertEqual(parser.get('engine', 'platforms'), 'windows')


class TheShellAnswersOnLinux(unittest.TestCase):

    def test_the_posix_layer_names_every_call_the_shell_makes(self):
        import re
        from src.shell import posix_shell
        used = set()
        for name in ('taskbar.py', 'desktop.py', 'start_menu.py', 'explorer.py', 'shell_manager.py',
                     'quick_launch.py'):
            with open(os.path.join(ROOT, 'src', 'shell', name), encoding='utf-8') as f:
                used.update(re.findall(r'win_shell\.([A-Za-z_]\w*)', f.read()))
        with open(os.path.join(ROOT, 'src', 'ui', 'start_menu_content.py'), encoding='utf-8') as f:
            used.update(re.findall(r'win_shell\.([A-Za-z_]\w*)', f.read()))
        from src.shell import win_shell
        missing = sorted(n for n in used if not hasattr(posix_shell, n) and hasattr(win_shell, n)
                         and callable(getattr(win_shell, n)))
        self.assertEqual(missing, [])

    def test_the_appbar_rectangle_and_the_poll_diff(self):
        from src.shell import posix_shell as p
        saved = p.screen_size
        p.screen_size = lambda: (1000, 600)
        try:
            bar = p.AppBar(0, edge=p.ABE_BOTTOM, height=30)
            self.assertTrue(bar.register())
            self.assertEqual(bar.reposition(), (0, 570, 1000, 600))
            bar.edge = p.ABE_TOP
            self.assertEqual(bar.reposition(40), (0, 0, 1000, 40))
        finally:
            p.screen_size = saved
        events = []
        hook = p.ShellHook(0, on_shell_event=lambda code, hwnd: events.append((code, hwnd)))
        hook._last = {1: ('A', False), 2: ('B', True)}
        saved_list = p.list_windows
        p.list_windows = lambda own=(): [p._shell_window(1, 'A', active=True), p._shell_window(3, 'C')]
        try:
            hook._stop.set()  # one pass, no waiting
            now = {w.hwnd: (w.title, w.active) for w in p.list_windows()}
            before, hook._last = hook._last, now
            for wid in now:
                if wid not in before:
                    hook._fire(p.HSHELL_WINDOWCREATED, wid)
            for wid in before:
                if wid not in now:
                    hook._fire(p.HSHELL_WINDOWDESTROYED, wid)
        finally:
            p.list_windows = saved_list
        self.assertIn((p.HSHELL_WINDOWCREATED, 3), events)
        self.assertIn((p.HSHELL_WINDOWDESTROYED, 2), events)

    def test_drives_have_the_shape_the_browser_reads(self):
        from src.shell import posix_shell as p
        if sys.platform == 'win32':
            self.skipTest('reads /proc/mounts')
        drives = p.list_drives()
        self.assertTrue(drives)
        for d in drives:
            for key in ('root', 'letter', 'label', 'type', 'total', 'free', 'name'):
                self.assertIn(key, d)


class ASoundThatDecodesToNothingIsNotPlayed(unittest.TestCase):

    def test_the_decoder_stands_aside_on_windows_and_without_tools(self):
        from src.titan_core import sound_decode as sd
        saved = sd.IS_WINDOWS
        try:
            sd.IS_WINDOWS = True
            self.assertIsNone(sd.decoded_copy(__file__))
            self.assertEqual(sd.why_unavailable(), '')
            sd.IS_WINDOWS = False
            self.assertIsNone(sd.decoded_copy('/nonexistent.ogg'))
        finally:
            sd.IS_WINDOWS = saved

    def test_the_players_refuse_an_empty_sound(self):
        import inspect
        from src.titan_core import sound
        self.assertIn('get_length() <= 0', inspect.getsource(sound._start_sound_file))
        self.assertIn('get_length() <= 0', inspect.getsource(sound._try_play_sound_from_path))


if __name__ == '__main__':
    unittest.main(verbosity=2)
