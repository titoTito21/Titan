# -*- coding: utf-8 -*-
"""The Titan system shell: the XP desktop, taskbar, notification area and menu.

The shell is what "Modify system interface" puts on the screen, so these
tests lock down the parts that decide whether it is correct rather than
merely present:

1. The Luna palette is DATA, and a skin can replace any of it - including
   asking for the classic grey shell instead - without touching the code
   that paints.
2. The appbar rectangle is computed in real pixels. Titan runs DPI-unaware,
   so a bar docked with this process's own coordinates reserves a strip
   several times too tall; this is the arithmetic that was actually wrong.
3. A window belongs on the taskbar by the same rule Alt+Tab uses, and the
   shell's own windows never appear on it.
4. The shell only starts when BOTH switches say so - the mode itself, and
   the part of it that takes over the screen.
5. The `shell.*` actions answer whether or not the shell's windows are up,
   name what they could not do, and ask rather than guess when a title
   matches more than one window.
6. The shell says nothing through TTS: the screen reader announces it, so
   `src/shell/` must not call Titan's speech at all.
7. The taskbar is navigable with the keyboard the way XP's is: Tab between
   the groups, the arrows inside one - which is what a bar of painted
   controls does NOT get for free, since every one of them asks wx for all
   the keys.
8. The notification area is read from the Windows the user has: Windows 11
   has no toolbar to send TB_* messages to, so the icons come out of UI
   Automation, and "Show hidden icons" is recognised by where it is rather
   than by a word in one language.
9. The desktop is a grid - filled column by column, snapped to a cell - and
   not a row of icons across the top of the screen.
10. Alt+F4 in any shell window means the Shut Down dialog, because the bar,
    the desktop and the Start menu have nothing to close and destroying one
    left the shell holding a dead frame.
11. The file browser - the shell's own Explorer over My Computer, drives and
    folders - answers the keys Explorer answers, and answers them where the
    keyboard actually is: Del while typing in the address field must never
    delete the selected files.
12. The shell's own three sounds (`sfx/<theme>/shell/`) say what the shell is
    doing - started, going away, gone somewhere - have a switch of their own,
    and fall back to the default set on a theme that does not carry them.
13. The shell settings are in real `wx.StaticBox` groups, which is what makes
    a screen reader say which group the keyboard has entered.
14. "Turn off TCE" in the Shut Down dialog is not a second kind of exit: it
    hands the exit to whichever face of Titan is running, so the confirmation
    the user asked for still appears and one teardown runs - and the shell is
    stopped, with its own goodbye sound, before Titan's.

Run directly: python tests/test_shell.py
"""

import os
import re
import sys
import types
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import wx                                                      # noqa: E402

_app = wx.App(False)                                           # noqa: E402

from src.shell import luna, win_shell                          # noqa: E402
from src.shell import shell_actions                            # noqa: E402


from src.titan_core.actions.interaction import (Failure,  # noqa: E402
                                                Question)
from src.titan_core.translation import _                       # noqa: E402


def said(result):
    """An action's answer as text, whether it worked, failed or asked."""
    if isinstance(result, Question):
        return "{} {}".format(result.prompt, ", ".join(result.options))
    for attribute in ('text', 'message', 'reason', 'prompt'):
        value = getattr(result, attribute, None)
        if value:
            return str(value)
    return str(result)


def asked(result):
    """True when the action stopped to ask rather than guessing."""
    return isinstance(result, Question)


def refused(result):
    """True when the action said plainly that it could not do it."""
    return isinstance(result, Failure)


class FakeSkin:
    def __init__(self, shell=None):
        self.shell = shell or {}


# --------------------------------------------------------------------------- #
# 1. The palette
# --------------------------------------------------------------------------- #
class PaletteTests(unittest.TestCase):

    def test_luna_is_the_default(self):
        palette = luna.Palette.from_skin(FakeSkin())
        self.assertEqual(palette.style, 'luna')
        self.assertEqual(palette.taskbar_height, 30)

    def test_luna_taskbar_gradient_is_the_measured_one(self):
        """The five bands of the real Luna taskbar, in order."""
        stops = luna.Palette.from_skin(FakeSkin())['taskbar_gradient']
        self.assertEqual([round(offset, 2) for offset, _colour in stops],
                         [0.0, 0.05, 0.18, 0.9, 1.0])
        first = stops[0][1]
        self.assertEqual((first.Red(), first.Green(), first.Blue()),
                         (0x38, 0x88, 0xe9))
        last = stops[-1][1]
        self.assertEqual((last.Red(), last.Green(), last.Blue()),
                         (0x19, 0x41, 0xa5))

    def test_a_skin_can_ask_for_the_classic_shell(self):
        palette = luna.Palette.from_skin(FakeSkin({'style': 'classic'}))
        self.assertEqual(palette.style, 'classic')
        # Classic is grey, not blue, and one pixel row shorter.
        colour = palette['taskbar_gradient'][0][1]
        self.assertEqual((colour.Red(), colour.Green(), colour.Blue()),
                         (0xc0, 0xc0, 0xc0))
        self.assertEqual(palette.taskbar_height, 28)

    def test_a_skin_can_replace_one_colour_and_keep_the_rest(self):
        palette = luna.Palette.from_skin(FakeSkin({
            'desktop_background': '#123456'}))
        colour = palette['desktop_background']
        self.assertEqual((colour.Red(), colour.Green(), colour.Blue()),
                         (0x12, 0x34, 0x56))
        self.assertEqual(palette.style, 'luna')       # everything else stands

    def test_a_skin_can_replace_a_whole_gradient(self):
        palette = luna.Palette.from_skin(FakeSkin({
            'taskbar_gradient': '#000000 0.0, #ffffff 1.0'}))
        stops = palette['taskbar_gradient']
        self.assertEqual(len(stops), 2)
        self.assertEqual(stops[1][1].Red(), 255)

    def test_a_broken_value_falls_back_instead_of_raising(self):
        palette = luna.Palette.from_skin(FakeSkin({
            'taskbar_gradient': 'not a gradient at all',
            'taskbar_height': 'tall'}))
        self.assertEqual(len(palette['taskbar_gradient']), 5)
        self.assertEqual(palette.taskbar_height, 30)

    def test_colours_parse_in_both_theme_notations(self):
        plain = luna.colour('#3888e9')
        self.assertEqual((plain.Red(), plain.Green(), plain.Blue()),
                         (0x38, 0x88, 0xe9))
        # Theme files write transparency first: #AARRGGBB.
        with_alpha = luna.colour('#803888e9')
        self.assertEqual(with_alpha.Alpha(), 0x80)
        self.assertEqual(with_alpha.Red(), 0x38)

    def test_the_bundled_xp_skin_declares_the_shell(self):
        import configparser
        path = os.path.join(REPO, 'skins', 'windows_xp', 'skin.ini')
        self.assertTrue(os.path.isfile(path), "the XP skin is missing")
        config = configparser.ConfigParser()
        config.read(path, encoding='utf-8')
        self.assertIn('Shell', config)
        palette = luna.Palette.from_skin(FakeSkin(dict(config['Shell'])))
        self.assertEqual(palette.style, 'luna')
        self.assertEqual(palette.taskbar_height, 30)
        # It must describe the same taskbar the defaults do.
        self.assertEqual(
            [round(offset, 2) for offset, _c in palette['taskbar_gradient']],
            [0.0, 0.05, 0.18, 0.9, 1.0])

    def test_the_classic_skins_ask_for_the_classic_shell(self):
        import configparser
        for name in ('windows95', 'retro'):
            path = os.path.join(REPO, 'skins', name, 'skin.ini')
            config = configparser.ConfigParser()
            config.read(path, encoding='utf-8')
            self.assertIn('Shell', config, f"{name} has no [Shell] section")
            palette = luna.Palette.from_skin(FakeSkin(dict(config['Shell'])))
            self.assertEqual(palette.style, 'classic', name)

    def test_skin_manager_reads_the_shell_section(self):
        from src.titan_core.skin_manager import Skin
        skin = Skin('windows_xp')
        self.assertTrue(skin.shell, "the [Shell] section was not loaded")
        self.assertEqual(skin.shell.get('style'), 'luna')


# --------------------------------------------------------------------------- #
# 2. Docking arithmetic
# --------------------------------------------------------------------------- #
class AppBarGeometryTests(unittest.TestCase):
    """The appbar answers in real pixels; Titan thinks in virtualised ones.

    This is the bug that made a 30 pixel taskbar reserve 152: the rectangle
    was computed from `GetSystemMetrics` (virtualised) and handed to
    `SHAppBarMessage` (not).
    """

    def setUp(self):
        self._screen = win_shell.screen_size
        self._physical = win_shell.physical_screen_size

    def tearDown(self):
        win_shell.screen_size = self._screen
        win_shell.physical_screen_size = self._physical

    def _pretend(self, logical, physical):
        win_shell.screen_size = lambda: logical
        win_shell.physical_screen_size = lambda: physical

    def test_scale_is_one_when_nothing_is_scaled(self):
        self._pretend((1920, 1080), (1920, 1080))
        self.assertAlmostEqual(win_shell.dpi_scale(), 1.0)

    def test_scale_follows_the_real_screen(self):
        self._pretend((1024, 640), (1280, 800))
        self.assertAlmostEqual(win_shell.dpi_scale(), 1.25)

    def test_the_docked_rectangle_is_scaled_up_and_reported_back_down(self):
        self._pretend((1024, 640), (1280, 800))
        sent = {}

        class FakeShell32:
            def SHAppBarMessage(self, message, data_ref):
                data = data_ref._obj
                sent[message] = (data.rc.left, data.rc.top,
                                 data.rc.right, data.rc.bottom)
                return 1

        original = win_shell.shell32
        win_shell.shell32 = FakeShell32()
        try:
            bar = win_shell.AppBar(hwnd=1, edge=win_shell.ABE_BOTTOM,
                                   height=30)
            bar.registered = True
            rect = bar.reposition()
        finally:
            win_shell.shell32 = original

        # Asked for in real pixels: 30 of Titan's is 37.5 real, and the strip
        # is rounded up rather than down so it can never be under-reserved.
        requested = sent[win_shell.ABM_SETPOS]
        self.assertEqual(requested[3], 800)
        self.assertEqual(requested[3] - requested[1], 38)
        self.assertEqual(requested[2], 1280)
        # Handed back in Titan's own, so it can go straight into wx.
        self.assertEqual(rect[1], 610)
        self.assertEqual(rect[3], 30)
        self.assertEqual(rect[2], 1024)

    def test_a_top_bar_is_measured_from_the_top(self):
        self._pretend((1000, 1000), (1000, 1000))
        sent = {}

        class FakeShell32:
            def SHAppBarMessage(self, message, data_ref):
                data = data_ref._obj
                sent[message] = (data.rc.top, data.rc.bottom)
                return 1

        original = win_shell.shell32
        win_shell.shell32 = FakeShell32()
        try:
            bar = win_shell.AppBar(hwnd=1, edge=win_shell.ABE_TOP, height=40)
            bar.registered = True
            bar.reposition()
        finally:
            win_shell.shell32 = original
        self.assertEqual(sent[win_shell.ABM_SETPOS], (0, 40))


# --------------------------------------------------------------------------- #
# 3. What belongs on the taskbar
# --------------------------------------------------------------------------- #
class WindowListTests(unittest.TestCase):

    def test_a_window_carries_its_state(self):
        window = win_shell.ShellWindow(42, title='Notepad', minimized=True)
        self.assertEqual(window.hwnd, 42)
        self.assertTrue(window.minimized)
        self.assertFalse(window.active)
        self.assertEqual(window, win_shell.ShellWindow(42))
        self.assertNotEqual(window, win_shell.ShellWindow(43))

    def test_the_shells_own_windows_are_never_listed(self):
        """Titan's taskbar must not grow a button for Titan's taskbar."""
        self.assertFalse(win_shell.is_taskbar_window(1234, own_hwnds=(1234,)))

    def test_the_live_list_agrees_with_the_rule(self):
        if not win_shell.available():
            self.skipTest("Windows only")
        windows = win_shell.list_windows()
        for window in windows:
            self.assertTrue(window.title.strip(),
                            "a window with no title got a taskbar button")
            self.assertTrue(win_shell.is_taskbar_window(window.hwnd))
        # At most one window is the active one.
        self.assertLessEqual(len([w for w in windows if w.active]), 1)


# --------------------------------------------------------------------------- #
# 4. When the shell may run at all
# --------------------------------------------------------------------------- #
class EnablementTests(unittest.TestCase):

    def setUp(self):
        from src.shell import shell_manager
        self.manager = shell_manager
        import src.titan_core.tce_system as tce_system
        self.tce = tce_system
        self._mode = tce_system.is_shell_mode_enabled
        self._setting = shell_manager.shell_setting

    def tearDown(self):
        self.tce.is_shell_mode_enabled = self._mode
        self.manager.shell_setting = self._setting

    def _pretend(self, mode_on, desktop_on):
        self.tce.is_shell_mode_enabled = lambda: mode_on
        self.manager.shell_setting = \
            lambda key, default: desktop_on if key == 'desktop_shell' \
            else default

    def test_off_when_the_mode_is_off(self):
        self._pretend(mode_on=False, desktop_on=True)
        self.assertFalse(self.manager.desktop_shell_enabled())

    def test_off_when_only_the_keyboard_half_is_wanted(self):
        self._pretend(mode_on=True, desktop_on=False)
        self.assertFalse(self.manager.desktop_shell_enabled())

    def test_on_when_both_switches_agree(self):
        self._pretend(mode_on=True, desktop_on=True)
        self.assertTrue(self.manager.desktop_shell_enabled())

    def test_start_shell_refuses_unless_asked(self):
        self._pretend(mode_on=False, desktop_on=False)
        self.assertFalse(self.manager.start_shell())

    def test_every_windows_shortcut_has_something_to_do(self):
        """A shortcut Titan takes from Windows must do the Windows thing.

        The mode suppresses these keys system wide, so a binding with no
        handler does not fall back - it swallows the shortcut.
        """
        from src.titan_core import tce_system
        manager = tce_system.SystemHooksManager()
        descriptions = tce_system.get_binding_descriptions()
        for binding_id, keys, label, _default in tce_system.SHELL_BINDINGS:
            self.assertIn(binding_id, descriptions, binding_id)
            if not keys:
                continue          # the bare Windows tap, handled separately
            self.assertTrue(hasattr(manager, f'_handle_{binding_id}'),
                            f"{label} ({binding_id}) has no handler")
        for binding_id, combo, label, _default in \
                tce_system.EXTRA_SHELL_BINDINGS:
            self.assertIn(binding_id, descriptions, binding_id)
            self.assertTrue(hasattr(manager, f'_handle_{binding_id}'),
                            f"{label} ({binding_id}) has no handler")

    def test_the_windows_shortcuts_reach_the_shell(self):
        """With the shell up, Windows' own shortcuts drive Titan's shell."""
        from src.titan_core import tce_system
        source = open(os.path.join(REPO, 'src', 'titan_core',
                                   'tce_system.py'), encoding='utf-8').read()
        for handler in ('_toggle_start_menu', '_handle_show_desktop',
                        '_handle_system_tray', '_handle_taskbar',
                        '_handle_minimize_all'):
            body = source.split(f'def {handler}')[1].split('\n    def ')[0]
            self.assertIn('shell_manager', body,
                          f"{handler} never asks the shell")
        ids = {binding[0] for binding in tce_system.SHELL_BINDINGS}
        # The shortcuts a Windows user expects of a shell.
        for expected in ('start_menu', 'show_desktop', 'run_dialog',
                         'file_manager', 'system_tray', 'taskbar',
                         'minimize_all', 'find'):
            self.assertIn(expected, ids)
        self.assertIn('start_menu_ctrl_esc',
                      {b[0] for b in tce_system.EXTRA_SHELL_BINDINGS})

    def test_the_settings_panel_offers_every_shell_option(self):
        """Each option the shell reads must be settable in Settings."""
        with open(os.path.join(REPO, 'src', 'ui', 'settingsgui.py'),
                  encoding='utf-8') as handle:
            source = handle.read()
        panel = source.split('def InitTitanShellPanel')[1][:4000]
        for option in ('desktop_shell', 'show_desktop', 'show_taskbar',
                       'show_tray', 'hide_system_taskbar', 'show_wallpaper',
                       'clock_seconds', 'auto_arrange_icons', 'focus_cues'):
            self.assertIn(option, panel, f"{option} is not in the settings")


# --------------------------------------------------------------------------- #
# 5. The actions
# --------------------------------------------------------------------------- #
class MenuGlyphTests(unittest.TestCase):
    """A menu entry says what it is; it does not draw it in text."""

    def test_a_branch_is_a_branch_and_does_not_say_so_in_words(self):
        """It is a tree: the control reports "collapsed" and "expanded"
        itself, so neither a glyph nor the word belongs in the text."""
        from src.shell.start_menu import MenuEntry, MenuTree
        frame = wx.Frame(None)
        try:
            tree = MenuTree(frame, lambda entry: None,
                            lambda entry: [MenuEntry('Inside', 'action')],
                            wx.WHITE, wx.BLACK, 'Test')
            tree.set_entries([MenuEntry('Programs', 'folder'),
                              MenuEntry('Run', 'action')])
            root = tree.GetRootItem()
            folder, cookie = tree.GetFirstChild(root)
            plain = tree.GetNextChild(root, cookie)[0]
            self.assertEqual(tree.GetItemText(folder), 'Programs')
            self.assertEqual(tree.GetItemText(plain), 'Run')
            self.assertTrue(tree.ItemHasChildren(folder))
            self.assertFalse(tree.ItemHasChildren(plain))
            for char in tree.GetItemText(folder) + tree.GetItemText(plain):
                self.assertLess(ord(char), 0x2000,
                                f"a glyph is being read out: {char!r}")
        finally:
            frame.Destroy()


class ForegroundTests(unittest.TestCase):
    """Switching windows must never pull the keyboard onto the bar."""

    def _watch_z_order(self, bar):
        ordered = []
        bar._set_z_order = lambda topmost=True, bottom=False: ordered.append(
            (topmost, bottom))
        return ordered

    def test_a_full_screen_app_coming_and_going_never_activates_the_bar(self):
        bar = _bar_with(windows=('Notepad',))
        raised = []
        bar.Raise = lambda: raised.append(True)
        bar.always_on_top = lambda: True
        ordered = self._watch_z_order(bar)
        try:
            bar._on_fullscreen(True)
            bar._on_fullscreen(False)
            # Behind everything, then back on top - and `Raise()` never,
            # because on Windows it calls SetForegroundWindow.
            self.assertEqual(ordered, [(False, True), (True, False)])
            self.assertEqual(raised, [])
        finally:
            bar.undock()
            bar.Destroy()

    def test_the_bar_lives_in_the_background_unless_it_is_asked_not_to(self):
        """Not topmost is a place in the z-order, not just a style bit."""
        bar = _bar_with()
        ordered = self._watch_z_order(bar)
        try:
            self.assertFalse(bar.always_on_top(),
                             "the bar covers other windows by default")
            bar.apply_always_on_top()
            # Down to the bottom, not merely told it is no longer topmost.
            self.assertEqual(ordered, [(False, True)])
        finally:
            bar.undock()
            bar.Destroy()

    def test_the_desktop_is_put_back_under_the_bar(self):
        """Both are at the bottom, so the order between them is decided."""
        bar = _bar_with()
        self._watch_z_order(bar)
        sent = []
        bar.shell.desktop = types.SimpleNamespace(
            send_to_back=lambda: sent.append(True))
        try:
            bar.send_to_background()
            self.assertEqual(sent, [True])
        finally:
            bar.shell.desktop = None
            bar.undock()
            bar.Destroy()


class TrayFurnitureTests(unittest.TestCase):
    """Windows' own clock and Show Desktop are not icons of Titan's tray."""

    def make(self, class_name, text):
        from src.system.tray_icons import SystemTrayIcon
        return SystemTrayIcon(text=text, class_name=class_name)

    def test_the_clock_is_recognised_by_the_time_it_shows(self):
        from src.system import tray_icons
        clock = self.make('SystemTray.OmniButton', 'Zegar 23:01')
        self.assertTrue(tray_icons.is_clock(clock))
        # A button that merely mentions a time is not the clock.
        volume = self.make('SystemTray.OmniButtonCenter', 'Volume 23:01')
        self.assertFalse(tray_icons.is_clock(volume))
        plain = self.make('SystemTray.OmniButton', 'Something')
        self.assertFalse(tray_icons.is_clock(plain))

    def test_show_desktop_is_recognised_by_its_class(self):
        from src.system import tray_icons
        button = self.make('SystemTray.ShowDesktopButton', 'Pokaz pulpit')
        self.assertTrue(tray_icons.is_show_desktop(button))
        self.assertFalse(tray_icons.is_show_desktop(
            self.make('SystemTray.NormalButton', 'OneDrive')))

    def test_the_bar_leaves_out_what_it_draws_itself(self):
        from src.shell import taskbar as taskbar_module
        bar = _bar_with()
        try:
            self.assertTrue(bar._is_titans_own(
                self.make('SystemTray.ShowDesktopButton', 'Show desktop')))
            self.assertTrue(bar._is_titans_own(
                self.make('SystemTray.OmniButton', 'Clock 23:01')))
            self.assertFalse(bar._is_titans_own(
                self.make('SystemTray.NormalButton', 'OneDrive')))
        finally:
            bar.undock()
            bar.Destroy()
        del taskbar_module


class TaskbarPropertiesTests(unittest.TestCase):
    """The sheet ReactOS' trayprop.cpp puts up, page for page."""

    def setUp(self):
        from src.shell.taskbar_properties import TaskbarPropertiesDialog
        self.dialog = TaskbarPropertiesDialog(None, None)
        self.addCleanup(self.dialog.Destroy)

    def pages(self):
        book = self.dialog.notebook
        return [book.GetPageText(i) for i in range(book.GetPageCount())]

    def test_it_has_the_three_pages(self):
        self.assertEqual(len(self.pages()), 3)

    def test_a_locked_taskbar_cannot_be_moved_from_here(self):
        """The control that moves it says so rather than doing nothing."""
        page = self.dialog.notebook.GetPage(0)
        page.lock.SetValue(True)
        page._locked_changed(True)
        self.assertFalse(page.position.IsEnabled())
        page.lock.SetValue(False)
        page._locked_changed(False)
        self.assertTrue(page.position.IsEnabled())

    def test_seconds_belong_to_a_clock_that_is_there(self):
        page = self.dialog.notebook.GetPage(2)
        page.clock.SetValue(False)
        page._sync_seconds()
        self.assertFalse(page.seconds.IsEnabled())
        page.clock.SetValue(True)
        page._sync_seconds()
        self.assertTrue(page.seconds.IsEnabled())

    def test_it_works_with_no_shell_running(self):
        """Every page is a setting on disk; the bar is only told as well."""
        self.assertIsNone(self.dialog.taskbar())
        self.assertIsNone(self.dialog.taskbar_do('set_position', 'top'))

    def test_a_change_reaches_the_running_bar(self):
        class FakeBar:
            def __init__(self):
                self.moved = None

            def set_position(self, name):
                self.moved = name
                return True

        class FakeShell:
            pass

        shell = FakeShell()
        shell.taskbar = FakeBar()
        self.dialog.shell = shell
        self.dialog.taskbar_do('set_position', 'left')
        self.assertEqual(shell.taskbar.moved, 'left')


class ActionTests(unittest.TestCase):

    def setUp(self):
        self._list = win_shell.list_windows
        self._activate = win_shell.activate_window
        self._close = win_shell.close_window

    def tearDown(self):
        win_shell.list_windows = self._list
        win_shell.activate_window = self._activate
        win_shell.close_window = self._close

    def _windows(self, *titles):
        made = [win_shell.ShellWindow(index + 1, title=title)
                for index, title in enumerate(titles)]
        win_shell.list_windows = lambda *args, **kwargs: made
        return made

    def test_every_action_is_declared_with_a_callable(self):
        for name, summary, params, risk, run in \
                shell_actions.get_shell_actions():
            self.assertTrue(name and summary, name)
            self.assertTrue(callable(run), name)
            self.assertIn(risk, ('auto', 'confirm', 'always_confirm', 'safe'))
            for param, spec in params.items():
                self.assertIn('type', spec, f"{name}.{param}")
                self.assertTrue(spec.get('description'), f"{name}.{param}")

    def test_the_registry_offers_them(self):
        from src.titan_core.actions import builtin
        addon = builtin._shell_addon()
        self.assertEqual(addon.addon_id, 'shell')
        names = {action.name for action in addon.actions}
        for expected in ('status', 'list_windows', 'activate_window',
                         'open_start_menu', 'show_desktop', 'list_desktop',
                         'open_desktop_item', 'list_tray', 'set_setting'):
            self.assertIn(expected, names)
        self.assertTrue(all(callable(action.run) for action in addon.actions))
        self.assertIn('shell', builtin.BUILTIN_IDS)

    def test_no_action_needs_the_ai(self):
        """The shell is a titan-core capability; nothing here calls a model."""
        from src.titan_core.actions import builtin
        for action in builtin._shell_addon().actions:
            self.assertFalse(action.needs_ai, action.name)
            self.assertNotIn(f'shell.{action.name}', builtin._AI_ACTIONS)

    def test_list_windows_numbers_them_and_marks_the_active_one(self):
        made = self._windows('Notepad', 'Calculator')
        made[1].active = True
        answer = shell_actions.shell_list_windows()
        self.assertIn('1. Notepad', answer)
        self.assertIn('2. Calculator', answer)
        self.assertEqual(len(answer.splitlines()), 2)

    def test_list_windows_says_so_when_there_are_none(self):
        self._windows()
        # Compared through the catalogue: Titan may be running in Polish,
        # and an answer being translated is correct, not a failure.
        self.assertEqual(shell_actions.shell_list_windows(),
                         _("No windows are open."))

    def test_activate_matches_a_partial_title(self):
        self._windows('Untitled - Notepad')
        chosen = {}
        win_shell.activate_window = lambda hwnd: chosen.setdefault('hwnd',
                                                                   hwnd) or True
        result = shell_actions.shell_activate_window(title='notepad')
        self.assertEqual(chosen['hwnd'], 1)
        self.assertIn('Notepad', said(result))

    def test_activate_asks_when_the_title_matches_two_windows(self):
        self._windows('Report - Word', 'Budget - Word')
        result = shell_actions.shell_activate_window(title='word')
        self.assertTrue(asked(result),
                        "an ambiguous title must ask, not guess")
        self.assertEqual(sorted(result.options),
                         ['Budget - Word', 'Report - Word'])

    def test_activate_without_a_title_asks_for_one(self):
        result = shell_actions.shell_activate_window()
        self.assertTrue(asked(result))
        self.assertEqual(result.name, 'title')

    def test_activate_fails_by_name_when_there_is_no_such_window(self):
        self._windows('Notepad')
        result = shell_actions.shell_activate_window(title='Photoshop')
        self.assertTrue(refused(result))
        self.assertIn('Photoshop', said(result))

    def test_arrange_rejects_an_unknown_arrangement_by_offering_the_real_ones(self):
        result = shell_actions.shell_arrange_windows(how='diagonally')
        self.assertTrue(asked(result))
        self.assertEqual(result.options,
                         ['cascade', 'horizontal', 'vertical'])

    def test_status_is_honest_when_the_shell_is_not_running(self):
        self.assertEqual(shell_actions.shell_status(),
                         _("The Titan shell is not running."))

    def test_actions_that_need_the_shell_say_so(self):
        # focus_desktop is deliberately not here: the desktop exists whether
        # or not Titan is drawing it, so that action falls back to Windows'
        # own rather than refusing.
        for action in (shell_actions.shell_focus_taskbar,
                       shell_actions.shell_focus_tray,
                       shell_actions.shell_open_start_menu):
            result = action()
            self.assertTrue(refused(result), action.__name__)
            self.assertEqual(said(result), _(
                "The Titan shell is not running. Turn on \"Replace the "
                "desktop, taskbar and Start menu\" under Settings, Titan "
                "shell."))

    def test_the_clock_action_answers_with_a_time_and_a_date(self):
        answer = shell_actions.shell_get_time()
        self.assertRegex(answer, r'\d{1,2}:\d{2}')
        self.assertRegex(answer, r'\d{4}')

    def test_list_settings_names_every_setting_the_shell_reads(self):
        answer = shell_actions.shell_list_settings()
        for label in ('taskbar', 'wallpaper', 'desktop shell'):
            self.assertIn(label, answer)

    def test_set_setting_refuses_a_name_that_does_not_exist(self):
        result = shell_actions.shell_set_setting(name='hyperdrive',
                                                 value='on')
        self.assertTrue(refused(result))
        self.assertIn('hyperdrive', said(result))

    def test_set_setting_asks_when_told_nothing(self):
        result = shell_actions.shell_set_setting()
        self.assertTrue(asked(result))
        self.assertIn('taskbar', result.options)

    def test_desktop_items_are_listed_and_openable_by_number(self):
        opened = {}
        real_folders = win_shell.desktop_folders
        real_open = win_shell.open_path
        real_name = win_shell.file_display_name
        import tempfile
        folder = tempfile.mkdtemp()
        try:
            for name in ('Alpha.txt', 'Beta.txt'):
                open(os.path.join(folder, name), 'w').close()
            win_shell.desktop_folders = lambda: [folder]
            win_shell.file_display_name = \
                lambda path: os.path.splitext(os.path.basename(path))[0]
            win_shell.open_path = lambda path: opened.setdefault('path', path) \
                or True

            listing = shell_actions.shell_list_desktop()
            self.assertIn('1. Alpha', listing)
            self.assertIn('2. Beta', listing)

            result = shell_actions.shell_open_desktop_item(name='2')
            self.assertTrue(opened['path'].endswith('Beta.txt'))
            self.assertIn('Beta', said(result))

            opened.clear()
            shell_actions.shell_open_desktop_item(name='alpha')
            self.assertTrue(opened['path'].endswith('Alpha.txt'))

            missing = shell_actions.shell_open_desktop_item(name='Gamma')
            self.assertTrue(refused(missing))
            self.assertIn('Gamma', said(missing))
        finally:
            win_shell.desktop_folders = real_folders
            win_shell.open_path = real_open
            win_shell.file_display_name = real_name
            import shutil
            shutil.rmtree(folder, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 6. The shell keeps quiet
# --------------------------------------------------------------------------- #
class SilenceTests(unittest.TestCase):
    """The screen reader announces the shell; the shell must not announce
    itself, or every button is spoken twice."""

    SPEECH = re.compile(r'\b(speak_stereo|speak_async|\.speak\(|'
                        r'accessible_output3|say_text)\b')

    def test_no_module_speaks(self):
        folder = os.path.join(REPO, 'src', 'shell')
        offenders = []
        for name in sorted(os.listdir(folder)):
            if not name.endswith('.py'):
                continue
            with open(os.path.join(folder, name), encoding='utf-8') as handle:
                for number, line in enumerate(handle, start=1):
                    if line.lstrip().startswith(('#', '*')):
                        continue
                    if self.SPEECH.search(line):
                        offenders.append(f"{name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [],
                         "the shell must not speak - the screen reader does")

    def test_controls_publish_a_name_a_role_and_a_state_instead(self):
        from src.shell.a11y import AccessibleMixin
        for method in ('shell_name', 'shell_role', 'shell_state',
                       'shell_activate', 'install_accessibility',
                       'notify_focus_event'):
            self.assertTrue(hasattr(AccessibleMixin, method), method)

    def test_focus_cues_are_a_setting_and_are_not_speech(self):
        from src.shell import a11y
        real = a11y.shell_setting
        played = []
        a11y.play_sound = lambda *args, **kwargs: played.append(args)
        try:
            a11y.shell_setting = lambda key, default: False
            a11y.focus_cue(0.0)
            self.assertEqual(played, [], "a cue played with cues turned off")
            a11y.shell_setting = lambda key, default: True
            a11y.focus_cue(0.0)
            self.assertEqual(len(played), 1)
        finally:
            a11y.shell_setting = real


# --------------------------------------------------------------------------- #
# 7. The windows themselves
# --------------------------------------------------------------------------- #
class ShellWindowTests(unittest.TestCase):
    """Building the real frames, without docking them to the screen."""

    def test_the_taskbar_builds_with_every_part_named(self):
        from src.shell.shell_manager import TitanShell
        from src.shell.taskbar import TaskbarFrame
        shell = TitanShell()
        bar = TaskbarFrame(shell)
        try:
            self.assertTrue(bar.start_button.shell_name())
            self.assertTrue(bar.clock.shell_name())
            self.assertTrue(bar.show_desktop_button.shell_name())
            # The name a screen reader reads is the one wx publishes.
            self.assertEqual(bar.start_button.GetName(),
                             bar.start_button.shell_name())
            self.assertRegex(bar.clock.get_text(), r'\d{1,2}:\d{2}')
            self.assertTrue(bar.start_button.AcceptsFocus())
        finally:
            bar.undock()
            bar.Destroy()

    def test_task_buttons_are_named_after_their_window_and_say_its_state(self):
        from src.shell.shell_manager import TitanShell
        from src.shell.taskbar import TaskbarFrame, TaskButton
        shell = TitanShell()
        bar = TaskbarFrame(shell)
        try:
            window = win_shell.ShellWindow(1, title='Notepad', minimized=True)
            button = TaskButton(bar.task_area, window, bar)
            self.assertEqual(button.shell_name(), 'Notepad')
            self.assertTrue(button.shell_description())
            self.assertEqual(button.button_state(), 'normal')
            window.active, window.minimized = True, False
            self.assertEqual(button.button_state(), 'active')
            window.flashing = True
            self.assertEqual(button.button_state(), 'flashing')
        finally:
            bar.undock()
            bar.Destroy()

    def test_the_start_menu_is_a_tree_that_opens_where_it_stands(self):
        """A branch fills itself when it is opened, and nothing in the text
        says it is a branch - the tree control says that itself."""
        from src.shell.start_menu import XPStartMenu
        menu = XPStartMenu(None, shell=None)
        tree = menu.left_tree
        try:
            self.assertTrue(menu.left_tree.entries)
            self.assertTrue(menu.right_list.entries)
            root = tree.GetRootItem()
            item, cookie = tree.GetFirstChild(root)
            branches = []
            while item.IsOk():
                entry = tree.GetItemData(item)
                if entry is not None and entry.kind == 'folder':
                    branches.append(item)
                    self.assertTrue(tree.ItemHasChildren(item))
                    self.assertEqual(tree.GetItemText(item), entry.label,
                                     "the text says more than the name")
                item, cookie = tree.GetNextChild(root, cookie)
            self.assertTrue(branches, "the menu has no branches at all")
            tree.Expand(branches[0])
            first = tree.GetFirstChild(branches[0])[0]
            self.assertTrue(first.IsOk())
            self.assertTrue(tree.GetItemText(first))
        finally:
            menu.Destroy()

    def test_the_desktop_reads_the_desktop_folders(self):
        from src.shell.desktop import DesktopFrame
        from src.shell.shell_manager import TitanShell
        import tempfile
        folder = tempfile.mkdtemp()
        real = win_shell.desktop_folders
        try:
            open(os.path.join(folder, 'Readme.txt'), 'w').close()
            os.makedirs(os.path.join(folder, 'Projects'))
            win_shell.desktop_folders = lambda: [folder]
            desktop = DesktopFrame(TitanShell())
            try:
                names = [entry['name'] for entry in desktop.items]
                self.assertIn('Projects', names)
                self.assertEqual(desktop.list.GetItemCount(), len(names))
                # Folders come before files, as they do in Explorer.
                self.assertEqual(names[0], 'Projects')
            finally:
                desktop.Destroy()
        finally:
            win_shell.desktop_folders = real
            import shutil
            shutil.rmtree(folder, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 8. The taskbar keyboard, as XP has it
# --------------------------------------------------------------------------- #
class FakeTrayIcon:
    """Enough of a tray icon for the bar to build a button on."""

    def __init__(self, text, chevron=False, hidden=False):
        self.text = text
        self.tooltip = text
        self.chevron = chevron
        self.hidden = hidden
        self.system = True
        self.pressed = 0
        self.key = (text,)

    def left_click(self):
        self.pressed += 1
        return True

    def right_click(self):
        return True


def _bar_with(windows=(), icons=(), launchers=('Chrome', 'Editor')):
    """A taskbar frame carrying a made-up window list, tray and band.

    The quick launch band reads a real folder, so a test that did not say
    what is in it would pass or fail depending on whose machine it ran on.
    """
    from src.shell.shell_manager import TitanShell
    from src.shell import taskbar as taskbar_module

    real_items = taskbar_module.quick_launch_items
    taskbar_module.quick_launch_items = lambda: [
        {'name': name, 'path': 'C:/' + name + '.lnk'} for name in launchers]
    try:
        bar = taskbar_module.TaskbarFrame(TitanShell())
    finally:
        taskbar_module.quick_launch_items = real_items
    bar.SetSize(0, 0, 1024, 30)
    bar._layout_bar()
    for title in windows:
        window = win_shell.ShellWindow(len(bar._buttons) + 1, title=title)
        bar._windows.append(window)
        bar._buttons[window.hwnd] = taskbar_module.TaskButton(
            bar.task_area, window, bar)
    bar._tray_buttons = [taskbar_module.TrayIconButton(bar.tray_area, icon, bar)
                         for icon in icons]
    bar._layout_bar()
    return bar


class TaskbarKeyboardTests(unittest.TestCase):
    """Tab walks the groups, the arrows walk what is in one."""

    def setUp(self):
        self.bar = _bar_with(windows=('Notepad', 'Calculator'),
                             icons=(FakeTrayIcon('Volume'),
                                    FakeTrayIcon('Network')))
        self.addCleanup(self._close)

    def _close(self):
        self.bar.undock()
        self.bar.Destroy()

    def names(self, controls):
        return [control.accessible_name for control in controls]

    def test_the_bar_is_the_four_groups_xp_has(self):
        self.assertEqual([name for name, _controls in self.bar.groups()],
                         ['start', 'quicklaunch', 'tasks', 'tray'])

    def test_the_clock_belongs_to_the_notification_area(self):
        tray = dict(self.bar.groups())['tray']
        self.assertIn(self.bar.clock, tray)
        # Show Desktop is the last thing on the bar, as it is on the bar
        # this one copies, and the clock is what comes before it.
        self.assertIs(tray[-1], self.bar.show_desktop_button)
        self.assertIs(tray[-2], self.bar.clock)
        self.assertEqual(len(tray), 4)

    def test_an_empty_group_is_not_a_stop_on_the_way_round(self):
        bar = _bar_with()
        try:
            self.assertEqual([name for name, _c in bar.groups()],
                             ['start', 'quicklaunch', 'tray'])
        finally:
            bar.undock()
            bar.Destroy()

    def test_tab_moves_to_the_next_group_and_wraps(self):
        self.bar.start_button.SetFocus()
        seen = []
        for _step in range(5):
            self.bar._move_between_groups(1)
            seen.append(wx.Window.FindFocus())
        self.assertEqual(self.names(seen[:4]),
                         [self.bar._quick_launch_buttons[0].accessible_name,
                          'Notepad', 'Volume',
                          self.bar.start_button.accessible_name])

    def test_shift_tab_goes_the_other_way(self):
        self.bar.start_button.SetFocus()
        self.bar._move_between_groups(-1)
        self.assertEqual(wx.Window.FindFocus().accessible_name, 'Volume')

    def test_coming_back_to_a_group_returns_to_where_it_was_left(self):
        self.bar._buttons[2].SetFocus()          # the second window button
        self.bar._move_between_groups(1)         # away, into the tray
        self.bar._move_between_groups(-1)        # and back
        self.assertEqual(wx.Window.FindFocus().accessible_name, 'Calculator')

    def test_the_arrows_move_inside_the_group_only(self):
        self.bar._buttons[1].SetFocus()
        self.assertTrue(self.bar._move_within_group(1))
        self.assertEqual(wx.Window.FindFocus().accessible_name, 'Calculator')
        # And they stop at the end of the group instead of leaving it.
        self.assertTrue(self.bar._move_within_group(1))
        self.assertEqual(wx.Window.FindFocus().accessible_name, 'Calculator')

    def test_home_and_end_go_to_the_ends_of_the_group(self):
        self.bar._tray_buttons[1].SetFocus()
        self.assertTrue(self.bar._move_to_group_end(False))
        self.assertEqual(wx.Window.FindFocus().accessible_name, 'Volume')
        self.assertTrue(self.bar._move_to_group_end(True))
        self.assertIs(wx.Window.FindFocus(), self.bar.show_desktop_button)

    def test_a_key_outside_the_bar_is_left_alone(self):
        self.assertFalse(self.bar._move_within_group(1))
        self.assertFalse(self.bar._move_to_group_end(True))

    def test_windows_b_lands_on_the_first_notification_icon(self):
        self.bar.focus_tray()
        self.assertEqual(wx.Window.FindFocus().accessible_name, 'Volume')

    def test_windows_b_lands_on_the_clock_when_there_are_no_icons(self):
        bar = _bar_with()
        try:
            bar.focus_tray()
            self.assertIs(wx.Window.FindFocus(), bar.clock)
        finally:
            bar.undock()
            bar.Destroy()

    def test_escape_hands_the_keyboard_back_to_where_it_came_from(self):
        handed = []
        real = win_shell.activate_window
        win_shell.activate_window = lambda hwnd: handed.append(hwnd) or True
        try:
            self.bar._previous_foreground = win_shell.user32.GetDesktopWindow()
            self.assertTrue(self.bar.hand_keyboard_back())
            self.assertEqual(handed, [win_shell.user32.GetDesktopWindow()])
            # And it is handed back once, not to every window ever seen.
            self.assertEqual(self.bar._previous_foreground, 0)
        finally:
            win_shell.activate_window = real

    def test_pressing_show_hidden_icons_expands_the_tray_instead_of_the_icon(self):
        chevron = FakeTrayIcon('Show hidden icons', chevron=True)
        bar = _bar_with(icons=(chevron,))
        asked = []
        bar.show_hidden_tray_icons = lambda: asked.append(True)
        try:
            bar._tray_buttons[0].shell_activate()
            self.assertEqual(asked, [True])
            self.assertEqual(chevron.pressed, 0)
        finally:
            bar.undock()
            bar.Destroy()

    def test_an_ordinary_icon_is_pressed(self):
        self.bar._tray_buttons[0].shell_activate()
        self.assertEqual(self.bar._tray_buttons[0].icon.pressed, 1)

    def test_the_notification_area_never_takes_half_the_bar(self):
        # The share is the *icons'* share; the clock and the Show Desktop
        # button are fixed furniture that is always there, so the bound
        # allows for them and still catches an icon strip growing without
        # limit (forty icons would fail this).
        bar = _bar_with(icons=[FakeTrayIcon(f"Icon {n}") for n in range(30)])
        try:
            self.assertLessEqual(bar._tray_width(), 1024 * 0.55)
            self.assertGreaterEqual(bar._tray_icon_width(), 14)
        finally:
            bar.undock()
            bar.Destroy()

    def test_the_quick_launch_band_is_the_folders_launchers(self):
        """The band is a row of the real folder's shortcuts, not one button."""
        self.assertEqual(self.names(dict(self.bar.groups())['quicklaunch']),
                         ['Chrome', 'Editor'])

    def test_the_band_reuses_its_buttons_across_a_refresh(self):
        """A refresh must not throw the keyboard out of the band."""
        from src.shell import taskbar as taskbar_module
        first = self.bar._quick_launch_buttons[0]
        first.SetFocus()
        real = taskbar_module.quick_launch_items
        taskbar_module.quick_launch_items = lambda: [
            {'name': 'Renamed', 'path': 'C:/Renamed.lnk'}]
        try:
            self.bar.refresh_quick_launch()
        finally:
            taskbar_module.quick_launch_items = real
        self.assertEqual(len(self.bar._quick_launch_buttons), 1)
        self.assertIs(self.bar._quick_launch_buttons[0], first)
        self.assertEqual(first.accessible_name, 'Renamed')

    def test_the_bar_can_stand_on_its_side(self):
        """A bar on the left is a column, not a row turned round."""
        from src.shell import taskbar as taskbar_module
        real = taskbar_module.shell_setting
        taskbar_module.shell_setting = lambda key, default: (
            'left' if key == 'taskbar_position' else default)
        try:
            self.assertFalse(self.bar.is_horizontal())
            self.bar.SetSize(0, 0, 100, 768)
            self.bar._layout_bar()
            start = self.bar.start_button.GetSize()
            self.assertEqual(start.width, 100)
            # The window buttons stack rather than sharing a row.
            first = self.bar._buttons[1].GetPosition()
            second = self.bar._buttons[2].GetPosition()
            self.assertEqual(first.x, second.x)
            self.assertGreater(second.y, first.y)
            # And the notification area is at the bottom of the column.
            tray = self.bar.tray_area.GetPosition()
            self.assertGreater(tray.y, first.y)
        finally:
            taskbar_module.shell_setting = real

    def test_the_bar_slides_off_the_edge_it_is_docked_to(self):
        """Hiding moves it out along the edge's own direction."""
        from src.shell import taskbar as taskbar_module
        real = taskbar_module.shell_setting

        def setting(key, default):
            if key == 'taskbar_auto_hide':
                return True
            if key == 'taskbar_position':
                return 'bottom'
            return real(key, default)

        taskbar_module.shell_setting = setting
        try:
            shown = self.bar._shown_rect()
            self.bar._auto_hide_offset = self.bar._auto_hide_extent()
            self.bar._apply_auto_hide()
            hidden_top = self.bar.GetPosition().y
            self.assertGreater(hidden_top, shown[1])
            # What is left behind is the sliver, so the bar never vanishes
            # from the screen altogether.
            self.assertEqual(shown[1] + shown[3] - hidden_top,
                             taskbar_module.AUTOHIDE_SLIVER)
        finally:
            taskbar_module.shell_setting = real
            self.bar._auto_hide_offset = 0

    def test_an_empty_folder_leaves_no_band_to_tab_through(self):
        bar = _bar_with(launchers=())
        try:
            self.assertNotIn('quicklaunch',
                             [name for name, _c in bar.groups()])
        finally:
            bar.undock()
            bar.Destroy()

    def test_a_renamed_icon_keeps_its_button_and_the_focus(self):
        from src.system import tray_icons
        first = [FakeTrayIcon('Battery: 40%'), FakeTrayIcon('Volume: 25%')]
        second = [FakeTrayIcon('Battery: 39%'), FakeTrayIcon('Volume: 25%')]
        for icons in (first, second):
            icons[0].key = ('battery',)
            icons[1].key = ('volume',)
        bar = _bar_with()
        real = tray_icons.get_tray_icons
        try:
            tray_icons.get_tray_icons = lambda include_hidden=True: first
            bar.refresh_tray()
            button = bar._tray_buttons[0]
            tray_icons.get_tray_icons = lambda include_hidden=True: second
            bar.refresh_tray()
            self.assertIs(bar._tray_buttons[0], button)
            self.assertEqual(button.accessible_name, 'Battery: 39%')
        finally:
            tray_icons.get_tray_icons = real
            bar.undock()
            bar.Destroy()


# --------------------------------------------------------------------------- #
# 9. The notification area itself
# --------------------------------------------------------------------------- #
class TrayReaderTests(unittest.TestCase):
    """What Windows 11 answers with, and what is made of it."""

    def setUp(self):
        from src.system import tray_icons
        self.tray = tray_icons

    def test_a_multi_line_tooltip_becomes_one_line(self):
        self.assertEqual(
            self.tray._clean('Network\r\nInternet access\n\nVPN\nConnected'),
            'Network - Internet access - VPN - Connected')

    def test_the_left_to_right_marks_windows_puts_in_dates_are_dropped(self):
        self.assertEqual(self.tray._clean('Clock 14:38\n\u200e11.\u200e08.\u200e2026'),
                         'Clock 14:38 - 11.08.2026')

    def test_an_icon_falls_back_to_a_name_rather_than_being_nameless(self):
        icon = self.tray.SystemTrayIcon(text='')
        self.assertTrue(icon.text)

    def test_an_icon_is_identified_by_what_windows_calls_it_not_by_its_name(self):
        icon = self.tray.SystemTrayIcon(text='Battery: 40%',
                                        runtime_id=(42, 7))
        renamed = self.tray.SystemTrayIcon(text='Battery: 39%',
                                           runtime_id=(42, 7))
        self.assertEqual(icon.key, renamed.key)

    def test_a_legacy_icon_is_identified_by_its_toolbar_and_command(self):
        icon = self.tray.SystemTrayIcon(text='Sync', hwnd=5, button_id=3)
        self.assertEqual(icon.key, (5, 3))

    def test_show_hidden_icons_is_found_by_where_it_is(self):
        chevron = self.tray.SystemTrayIcon(text='Pokaz ukryte ikony',
                                           automation_id='SystemTrayIcon',
                                           class_name='SystemTray.NormalButton')
        app_icon = self.tray.SystemTrayIcon(text='OneDrive',
                                            automation_id='NotifyItemIcon',
                                            class_name='SystemTray.NormalButton')
        icons = [chevron, app_icon]
        self.tray._mark_chevron(icons)
        self.assertTrue(self.tray.is_chevron(chevron))
        self.assertFalse(self.tray.is_chevron(app_icon))

    def test_an_applications_own_icon_is_never_taken_for_the_chevron(self):
        icons = [self.tray.SystemTrayIcon(text='OneDrive',
                                          automation_id='NotifyItemIcon',
                                          class_name='SystemTray.NormalButton')]
        self.tray._mark_chevron(icons)
        self.assertFalse(self.tray.is_chevron(icons[0]))

    def test_a_hidden_icon_says_so(self):
        icon = self.tray.SystemTrayIcon(text='NVDA', hidden=True)
        self.assertTrue(icon.hidden)

    def test_pressing_an_icon_tries_ui_automation_before_the_mouse(self):
        tried = []
        real_invoke = self.tray._uia_invoke
        real_click = self.tray._real_click
        self.tray._uia_invoke = lambda element: tried.append('uia') or True
        self.tray._real_click = lambda point, right=False: \
            tried.append('mouse') or True
        try:
            icon = self.tray.SystemTrayIcon(text='Volume', element=object(),
                                            rect=(0, 0, 10, 10))
            self.assertTrue(icon.left_click())
            self.assertEqual(tried, ['uia'])
        finally:
            self.tray._uia_invoke = real_invoke
            self.tray._real_click = real_click

    def test_a_click_is_the_fallback_when_ui_automation_will_not_do_it(self):
        clicked = []
        real_invoke = self.tray._uia_invoke
        real_click = self.tray._real_click
        self.tray._uia_invoke = lambda element: False
        self.tray._real_click = lambda point, right=False: \
            clicked.append((point, right)) or True
        try:
            icon = self.tray.SystemTrayIcon(text='Volume', element=object(),
                                            rect=(10, 20, 30, 40))
            self.assertTrue(icon.left_click())
            self.assertEqual(clicked, [((20, 30), False)])
        finally:
            self.tray._uia_invoke = real_invoke
            self.tray._real_click = real_click

    def test_a_hidden_icon_is_looked_up_again_when_its_flyout_has_closed(self):
        real_invoke = self.tray._uia_invoke
        real_expand = self.tray.expand_hidden_icons
        real_click = self.tray._real_click
        fresh = self.tray.SystemTrayIcon(text='NVDA', hidden=True,
                                         element='fresh element')
        calls = []

        def invoke(element):
            calls.append(element)
            return element == 'fresh element'

        self.tray._uia_invoke = invoke
        self.tray.expand_hidden_icons = lambda: [fresh]
        self.tray._real_click = lambda point, right=False: False
        try:
            stale = self.tray.SystemTrayIcon(text='NVDA', hidden=True,
                                             element='dead element')
            self.assertTrue(stale.left_click())
            self.assertEqual(calls, ['dead element', 'fresh element'])
            self.assertEqual(stale.element, 'fresh element')
        finally:
            self.tray._uia_invoke = real_invoke
            self.tray.expand_hidden_icons = real_expand
            self.tray._real_click = real_click

    def test_the_old_module_still_answers_for_anything_that_imports_it(self):
        from src.system import system_tray_list
        self.assertIs(system_tray_list.get_tray_icons, self.tray.get_tray_icons)
        self.assertIs(system_tray_list.SystemTrayIcon, self.tray.SystemTrayIcon)

    def test_the_live_notification_area_is_read(self):
        """The real one, on the real Windows this is running on."""
        if os.name != 'nt':
            self.skipTest('the notification area is a Windows thing')
        icons = self.tray.get_tray_icons(include_hidden=False)
        self.assertTrue(icons, "nothing at all was read from the tray")
        for icon in icons:
            self.assertTrue(icon.text.strip())
            self.assertNotIn('\n', icon.text)


# --------------------------------------------------------------------------- #
# 10. The desktop is a grid
# --------------------------------------------------------------------------- #
class DesktopGridTests(unittest.TestCase):

    def _desktop(self, count=6):
        from src.shell.desktop import DesktopFrame
        from src.shell.shell_manager import TitanShell
        import tempfile
        folder = tempfile.mkdtemp()
        self.folder = folder
        for index in range(count):
            open(os.path.join(folder, f"Item {index}.txt"), 'w').close()
        self.real_folders = win_shell.desktop_folders
        win_shell.desktop_folders = lambda: [folder]
        desktop = DesktopFrame(TitanShell())
        desktop.SetSize(0, 0, 800, 600)
        desktop.list.SetSize(0, 0, 800, 600)
        desktop.refresh()
        return desktop

    def tearDown(self):
        win_shell.desktop_folders = getattr(self, 'real_folders',
                                            win_shell.desktop_folders)
        import shutil
        shutil.rmtree(getattr(self, 'folder', ''), ignore_errors=True)

    def test_the_icons_are_a_grid_and_not_a_row(self):
        desktop = self._desktop(count=12)
        try:
            positions = [desktop.list.GetItemPosition(index)
                         for index in range(desktop.list.GetItemCount())]
            self.assertGreater(len({point.y for point in positions}), 1,
                               "every icon is on the same line - that is a row")
            # A desktop fills a column downwards before starting the next.
            self.assertEqual(positions[0].x, positions[1].x)
            self.assertGreater(positions[1].y, positions[0].y)
        finally:
            desktop.Destroy()

    def test_the_list_is_built_as_an_icon_view_aligned_to_the_left(self):
        desktop = self._desktop(count=2)
        try:
            style = desktop.list.GetWindowStyleFlag()
            self.assertTrue(style & wx.LC_ICON)
            self.assertTrue(style & wx.LC_ALIGN_LEFT)
            self.assertFalse(style & wx.LC_ALIGN_TOP)
        finally:
            desktop.Destroy()

    def test_alt_enter_asks_for_the_properties_rather_than_opening(self):
        desktop = self._desktop(count=2)
        done = []
        desktop.open_selected = lambda: done.append('open')
        desktop.properties_of_selected = lambda: done.append('properties')
        try:
            event = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
            event.SetKeyCode(wx.WXK_RETURN)
            event.SetControlDown(False)
            event.SetAltDown(True)
            desktop._on_key(event)
            self.assertEqual(done, ['properties'])
        finally:
            desktop.Destroy()


    def test_the_list_is_called_the_desktop_and_nothing_longer(self):
        """The list IS the desktop; "Desktop icons" said the word twice."""
        desktop = self._desktop(count=1)
        try:
            self.assertEqual(desktop.list.GetName(), _("Desktop"))
        finally:
            desktop.Destroy()

    def test_alt_f4_on_the_desktop_asks_the_computer_to_shut_down(self):
        """There is no window to close here, so Alt+F4 is Windows' own."""
        desktop = self._desktop(count=1)
        asked = []
        desktop.show_shutdown = lambda: asked.append(True) or True
        try:
            event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
            event.SetKeyCode(wx.WXK_F4)
            event.SetAltDown(True)
            desktop._on_char_hook(event)
            self.assertEqual(asked, [True])
        finally:
            desktop.Destroy()

    def test_a_desktop_item_is_opened_and_asked_about_through_the_shell(self):
        """Every desktop verb goes through a documented shell call."""
        desktop = self._desktop(count=1)
        calls = {}
        real_open = win_shell.open_path
        real_props = win_shell.show_properties
        real_reveal = win_shell.reveal_in_explorer
        win_shell.open_path = lambda path: calls.setdefault('open', path)
        win_shell.show_properties = lambda path, owner=0: calls.setdefault(
            'properties', (path, bool(owner)))
        win_shell.reveal_in_explorer = lambda path: calls.setdefault(
            'reveal', path)
        try:
            desktop.list.Select(0)
            desktop.list.Focus(0)
            path = desktop.items[0]['path']
            desktop.open_selected()
            desktop.properties_of_selected()
            desktop.open_location_of_selected()
            self.assertEqual(calls['open'], path)
            self.assertEqual(calls['properties'][0], path)
            self.assertTrue(calls['properties'][1],
                            "the property sheet has no owner window")
            self.assertEqual(calls['reveal'], path)
        finally:
            win_shell.open_path = real_open
            win_shell.show_properties = real_props
            win_shell.reveal_in_explorer = real_reveal
            desktop.Destroy()

    def test_renaming_keeps_the_extension_the_file_had(self):
        desktop = self._desktop(count=1)
        try:
            was = desktop.items[0]['path']
            # wx will not let a label-edit event be built with a label in
            # it, so the event is stood in for by what the handler asks of
            # it - which is the whole of the contract either way.
            event = types.SimpleNamespace(
                IsEditCancelled=lambda: False, GetIndex=lambda: 0,
                GetLabel=lambda: 'Renamed', Veto=lambda: None)
            desktop._on_rename(event)
            self.assertTrue(desktop.items[0]['path'].endswith('Renamed.txt'))
            self.assertFalse(os.path.exists(was))
            self.assertTrue(os.path.exists(desktop.items[0]['path']))
        finally:
            desktop.Destroy()


# --------------------------------------------------------------------------- #
# 10. What is said to the screen reader, and by whom
# --------------------------------------------------------------------------- #
class GroupAnnouncementTests(unittest.TestCase):
    """Arriving in a group of the bar is announced the way the tab bar is:
    through the screen reader alone, never through the platform TTS."""

    def test_nothing_is_said_when_no_screen_reader_is_running(self):
        from src.accessibility import messages
        real_ta = messages._ta_announce
        real_sr = messages.is_screen_reader_running
        real_speak = messages.speak_sr_only
        spoken = []
        messages._ta_announce = lambda *args, **kwargs: False
        messages.is_screen_reader_running = lambda: False
        messages.speak_sr_only = lambda *args, **kwargs: spoken.append(args)
        try:
            self.assertFalse(messages.announce_shell_group('Dock'))
            self.assertEqual(spoken, [])
        finally:
            messages._ta_announce = real_ta
            messages.is_screen_reader_running = real_sr
            messages.speak_sr_only = real_speak

    def test_the_reader_is_told_the_group_before_the_control(self):
        from src.shell import taskbar as taskbar_module
        bar = _bar_with(windows=('Notepad',),
                        icons=(FakeTrayIcon('Volume'),))
        said = []
        real = taskbar_module.announce_group
        taskbar_module.announce_group = lambda label: said.append(label)
        try:
            bar.start_button.SetFocus()
            bar._move_between_groups(1)      # into the quick launch band
            bar._move_between_groups(1)      # into the window buttons
            self.assertEqual(said, [taskbar_module.group_label('quicklaunch'),
                                    taskbar_module.group_label('tasks')])
            # The arrows move inside a group, which is not an arrival.
            said[:] = []
            bar._move_within_group(1)
            self.assertEqual(said, [])
        finally:
            taskbar_module.announce_group = real
            bar.undock()
            bar.Destroy()

    def test_every_group_has_words_of_its_own(self):
        from src.shell import taskbar as taskbar_module
        bar = _bar_with(windows=('Notepad',), icons=(FakeTrayIcon('Volume'),))
        try:
            labels = [taskbar_module.group_label(name)
                      for name, _controls in bar.groups()]
            self.assertTrue(all(labels), "a group with nothing to say")
            self.assertEqual(len(set(labels)), len(labels))
        finally:
            bar.undock()
            bar.Destroy()


# --------------------------------------------------------------------------- #
# 11. The Start menu is one ring of real controls
# --------------------------------------------------------------------------- #
class StartMenuKeyboardTests(unittest.TestCase):

    def setUp(self):
        from src.shell.start_menu import XPStartMenu
        self.menu = XPStartMenu(None, shell=None)
        self.addCleanup(self.menu.Destroy)

    def test_everything_in_the_menu_is_a_stop_on_the_ring(self):
        ring = self.menu.focus_ring()
        self.assertIn(self.menu.header, ring)
        self.assertIn(self.menu.search_field, ring)
        self.assertIn(self.menu.left_tree, ring)
        self.assertNotIn(self.menu.left_list, ring,
                         "the results list is a stop while it is hidden")
        self.assertIn(self.menu.right_list, ring)
        self.assertIn(self.menu.shutdown_button, ring)
        self.assertTrue(all(control.GetName() for control in ring),
                        "a stop on the ring with no name to read")

    def test_the_user_is_a_button_and_not_a_painted_strip(self):
        self.assertTrue(self.menu.header.AcceptsFocus())
        self.assertEqual(self.menu.header.GetName(),
                         self.menu.header.shell_name())
        self.assertTrue(self.menu.header.shell_name())

    def test_tab_goes_round_the_ring_and_shift_tab_comes_back(self):
        ring = self.menu.focus_ring()
        self.menu.header.SetFocus()
        self.menu._move_focus(1)
        self.assertIs(wx.Window.FindFocus(), ring[1])
        self.menu._move_focus(-1)
        self.assertIs(wx.Window.FindFocus(), ring[0])

    def test_the_search_finds_an_entry_by_part_of_its_name(self):
        target = self.menu.right_list.entries[0].label
        needle = target[1:4].lower()
        found = [entry.label for entry in self.menu.search_entries(needle)]
        self.assertIn(target, found)

    def test_a_name_that_starts_with_what_was_typed_comes_first(self):
        target = self.menu.right_list.entries[0].label
        entries = self.menu.search_entries(target[:3])
        self.assertTrue(entries)
        self.assertTrue(entries[0].label.lower().startswith(
            target[:3].lower()))

    def test_an_empty_search_is_the_menu_again(self):
        self.assertEqual(self.menu.search_entries(''), [])
        self.menu.search_field.SetValue('zzzz-nothing-matches')
        self.assertEqual(self.menu.left_list.entries, [])
        self.assertIs(self.menu.left_column(), self.menu.left_list)
        self.assertTrue(self.menu.clear_search())
        self.assertIs(self.menu.left_column(), self.menu.left_tree)
        self.assertTrue(self.menu.left_tree.entries)
        self.assertFalse(self.menu.clear_search())

    def test_the_column_says_how_many_were_found(self):
        self.menu.search_field.SetValue('a')
        name = self.menu.left_list.GetName()
        self.assertTrue(name)
        self.assertNotEqual(name, _("Programs"))


class StartMenuContentsTests(unittest.TestCase):
    """The menu carries everything Titan can start, not only programs."""

    def setUp(self):
        from src.shell.start_menu import XPStartMenu
        self.menu = XPStartMenu(None, shell=None)
        self.addCleanup(self.menu.Destroy)

    def test_the_column_has_a_branch_for_each_kind_of_thing(self):
        payloads = [entry.payload for entry in self.menu.left_tree.entries
                    if entry.kind == 'folder']
        for wanted in ('__apps__', '__games__', '__im__', '__macros__',
                       '__settings__', '__all_programs__'):
            self.assertIn(wanted, payloads)

    def test_titan_settings_live_under_settings_and_not_among_the_places(self):
        settings = [entry.payload for entry in self.menu._settings_entries()]
        self.assertIn('titan_settings', settings)
        places = [entry.payload for entry in self.menu._places_entries()]
        self.assertNotIn('titan_settings', places)

    def test_titans_own_messengers_are_in_the_menu_too(self):
        """Not only the installed modules: the ones Titan brings itself."""
        entries = self.menu._im_entries()
        builtin = [entry.payload for entry in entries
                   if entry.kind == 'im_builtin']
        for service in ('telegram', 'messenger', 'whatsapp', 'titannet',
                        'elten'):
            self.assertIn(service, builtin)

    def test_the_windows_apps_branch_is_what_windows_itself_lists(self):
        """UWP apps live nowhere else: no shortcut, only an app id."""
        entries = self.menu._windows_app_entries()
        self.assertTrue(entries)
        if entries[0].kind == 'separator':
            self.skipTest("this machine's Apps folder could not be read")
        self.assertTrue(all(entry.kind == 'uwp' for entry in entries))
        self.assertTrue(all(entry.payload for entry in entries))

    def test_the_im_modules_and_the_macros_are_branches_of_their_own(self):
        for payload in ('__im__', '__macros__'):
            entry = [e for e in self.menu.left_tree.entries
                     if e.payload == payload][0]
            children = self.menu._children_of(entry)
            self.assertTrue(children, payload)
            # Either real entries, or one saying there are none - never
            # an empty branch that opens onto nothing.
            kinds = {child.kind for child in children}
            self.assertTrue(
                kinds <= {'im_builtin', 'im_module', 'macro', 'separator'},
                kinds)

    def test_the_search_looks_inside_the_branches_too(self):
        # "There are no macros" is a line of the menu, not something that
        # can be found, so only the real entries are compared.
        labels = {entry.label for entry in self.menu._searchable_branches()
                  if entry.kind != 'separator'}
        self.assertTrue(labels, "the settings alone should be searchable")
        index = {entry.label for entry in self.menu._build_search_index()}
        self.assertTrue(labels <= index,
                        "the search does not cover the branches")

    def test_a_macro_and_a_module_know_how_to_be_started(self):
        from src.shell.start_menu import MenuEntry
        started = []
        self.menu._open_im_module = lambda info: started.append(('im', info))
        self.menu._run_macro = lambda macro: started.append(('macro', macro))
        self.menu._activate_entry(MenuEntry('X', 'im_module', {'id': 'x'}))
        self.menu._activate_entry(MenuEntry('Y', 'macro', {'name': 'y'}))
        self.assertEqual([kind for kind, _payload in started],
                         ['im', 'macro'])


class ShutdownDialogTests(unittest.TestCase):
    """The dialog is the machine's, plus the one thing that is Titan's."""

    def test_turning_titan_off_is_one_of_the_choices(self):
        from src.shell import shutdown_dialog
        ids = [action for action, _label, _desc in
               shutdown_dialog.shutdown_actions()]
        self.assertIn('exit_titan', ids)
        self.assertIn('shutdown', ids)
        for _id, label, description in shutdown_dialog.shutdown_actions():
            self.assertTrue(label and description)

    def test_it_closes_titan_and_not_windows(self):
        from src.shell import shutdown_dialog
        called = []
        real = shutdown_dialog.exit_titan
        real_exit = win_shell.exit_windows
        shutdown_dialog.exit_titan = lambda: called.append(True) or True
        win_shell.exit_windows = lambda mode: called.append(mode)
        try:
            self.assertTrue(
                shutdown_dialog.perform_shutdown_action('exit_titan'))
            self.assertEqual(called, [True])
        finally:
            shutdown_dialog.exit_titan = real
            win_shell.exit_windows = real_exit


# --------------------------------------------------------------------------- #
# 12. The shell's windows are furniture, not applications
# --------------------------------------------------------------------------- #
class FurnitureTests(unittest.TestCase):
    """A desktop, a taskbar and a Start menu are not three more programs."""

    def test_a_shell_window_is_taken_out_of_alt_tab(self):
        frame = wx.Frame(None, title='Furniture')
        try:
            frame.Show()
            self.assertTrue(win_shell.hide_from_alt_tab(frame.GetHandle()))
            self.assertFalse(win_shell.is_taskbar_window(frame.GetHandle()),
                             "a shell window still answers the Alt+Tab rule")
        finally:
            frame.Destroy()

    def test_the_bar_asks_wx_for_a_tool_window_too(self):
        bar = _bar_with()
        try:
            self.assertTrue(bar.GetWindowStyleFlag() & wx.FRAME_TOOL_WINDOW)
            self.assertTrue(bar.GetWindowStyleFlag() & wx.FRAME_NO_TASKBAR)
        finally:
            bar.undock()
            bar.Destroy()

    def test_escape_brings_a_hidden_bar_back_out(self):
        """Escape in the menu is how the taskbar is asked for."""
        from src.shell import taskbar as taskbar_module
        bar = _bar_with()
        bar.auto_hide = lambda: True
        bar._auto_hide_state = taskbar_module.AUTOHIDE_HIDDEN
        bar.take_foreground_called = []
        bar.Raise = lambda: None
        try:
            bar.focus_start_button()
            self.assertIn(bar._auto_hide_state,
                          (taskbar_module.AUTOHIDE_SHOWING,
                           taskbar_module.AUTOHIDE_SHOWN))
        finally:
            bar.undock()
            bar.Destroy()

    def test_escape_in_the_start_menu_lands_on_the_start_button(self):
        """As on Windows: the menu closes onto the button it came out of."""
        from src.shell.start_menu import XPStartMenu
        pressed = []
        shell = types.SimpleNamespace(
            focus_start_button=lambda: pressed.append(True) or True,
            set_start_button_pressed=lambda value: None,
            taskbar_height=lambda: 30)
        menu = XPStartMenu(None, shell=shell)
        try:
            event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
            event.SetKeyCode(wx.WXK_ESCAPE)
            menu._on_char_hook(event)
            self.assertEqual(pressed, [True])
            self.assertFalse(menu.IsShown())
        finally:
            menu.Destroy()


# --------------------------------------------------------------------------- #
# 13. The actions the new shell grew
# --------------------------------------------------------------------------- #
class NewActionTests(unittest.TestCase):

    def setUp(self):
        self.folder = None
        self.real_folders = win_shell.desktop_folders

    def tearDown(self):
        win_shell.desktop_folders = self.real_folders
        if self.folder:
            import shutil
            shutil.rmtree(self.folder, ignore_errors=True)

    def _desktop_folder(self, names=('Report.txt',)):
        import tempfile
        self.folder = tempfile.mkdtemp()
        for name in names:
            open(os.path.join(self.folder, name), 'w').close()
        win_shell.desktop_folders = lambda: [self.folder]
        return self.folder

    def test_every_new_action_is_declared_with_a_callable(self):
        declared = {name: handler for name, _summary, _params, _risk, handler
                    in shell_actions.get_shell_actions()}
        for name in ('focus_tray', 'desktop_item_properties',
                     'desktop_item_target', 'open_item_location',
                     'rename_desktop_item', 'delete_desktop_item',
                     'create_desktop_shortcut', 'search_programs',
                     'run_program', 'power_options', 'power'):
            self.assertIn(name, declared)
            self.assertTrue(callable(declared[name]), name)

    def test_turning_the_computer_off_always_asks_first(self):
        risks = {name: risk for name, _s, _p, risk, _h
                 in shell_actions.get_shell_actions()}
        self.assertEqual(risks['power'], 'always_confirm')
        for name in ('delete_desktop_item', 'rename_desktop_item',
                     'run_program', 'create_desktop_shortcut'):
            self.assertNotEqual(risks[name], 'auto', name)

    def test_power_offers_only_what_this_machine_will_do(self):
        answer = shell_actions.shell_power_options()
        self.assertIn('shutdown', answer)
        self.assertIn('exit_titan', answer)
        asked_for = shell_actions.shell_power()
        self.assertTrue(asked(asked_for))
        self.assertIn('exit_titan', asked_for.options)
        refusal = shell_actions.shell_power(action='fly')
        self.assertTrue(refused(refusal))

    def test_a_desktop_item_is_renamed_and_deleted_by_name(self):
        folder = self._desktop_folder(('Report.txt',))
        result = shell_actions.shell_rename_desktop_item(name='Report',
                                                         new_name='Notes')
        self.assertFalse(refused(result), said(result))
        self.assertTrue(os.path.exists(os.path.join(folder, 'Notes.txt')))
        self.assertFalse(os.path.exists(os.path.join(folder, 'Report.txt')))

    def test_renaming_asks_for_the_new_name_rather_than_inventing_one(self):
        self._desktop_folder(('Report.txt',))
        result = shell_actions.shell_rename_desktop_item(name='Report')
        self.assertTrue(asked(result))
        self.assertEqual(result.name, 'new_name')

    def test_an_ambiguous_desktop_name_is_asked_about(self):
        self._desktop_folder(('Report one.txt', 'Report two.txt'))
        result = shell_actions.shell_desktop_item_properties(name='Report')
        self.assertTrue(asked(result))
        self.assertEqual(len(result.options), 2)

    def test_a_shortcut_is_made_on_the_desktop_and_read_back(self):
        folder = self._desktop_folder(())
        target = os.path.join(folder, 'target.txt')
        open(target, 'w').close()
        result = shell_actions.shell_create_desktop_shortcut(target=target)
        if refused(result):
            self.skipTest("this machine has no WScript.Shell: " + said(result))
        links = [name for name in os.listdir(folder)
                 if name.lower().endswith('.lnk')]
        self.assertTrue(links)
        answer = shell_actions.shell_desktop_item_target(
            name=os.path.splitext(links[0])[0])
        self.assertIn('target.txt', said(answer))

    def test_creating_a_shortcut_to_nothing_says_so(self):
        self._desktop_folder(())
        result = shell_actions.shell_create_desktop_shortcut(
            target='C:/nothing/at/all.exe')
        self.assertTrue(refused(result))

    def test_the_search_reads_the_windows_start_menu_off_the_disk(self):
        """It must answer with no Start menu window open."""
        entries = shell_actions._windows_programs()
        self.assertTrue(entries, "no programs found in the Start Menu")
        for label, where, path in entries[:20]:
            self.assertTrue(label and where and os.path.exists(path))

    def test_searching_for_nothing_asks_what_for(self):
        result = shell_actions.shell_search_programs()
        self.assertTrue(asked(result))
        self.assertEqual(result.name, 'query')

    def test_the_shell_settings_include_the_new_ones(self):
        answer = shell_actions.shell_list_settings()
        for label in ('taskbar on top', 'quick launch', 'clock'):
            self.assertIn(label, answer)


# --------------------------------------------------------------------------- #
# 14. The keyboard really lands on the desktop, and the search really reads
# --------------------------------------------------------------------------- #
class DesktopFocusTests(unittest.TestCase):
    """Windows+M and Tab must leave the focus on the icons themselves."""

    def _desktop(self):
        from src.shell.desktop import DesktopFrame
        from src.shell.shell_manager import TitanShell
        import tempfile
        self.folder = tempfile.mkdtemp()
        for name in ('One.txt', 'Two.txt'):
            open(os.path.join(self.folder, name), 'w').close()
        self.real_folders = win_shell.desktop_folders
        win_shell.desktop_folders = lambda: [self.folder]
        desktop = DesktopFrame(TitanShell())
        desktop.refresh()
        return desktop

    def tearDown(self):
        win_shell.desktop_folders = getattr(self, 'real_folders',
                                            win_shell.desktop_folders)
        import shutil
        shutil.rmtree(getattr(self, 'folder', ''), ignore_errors=True)

    def test_the_focus_is_set_again_after_the_activation_goes_through(self):
        """wx answers WM_ACTIVATE by focusing the frame, undoing the first
        SetFocus - which is why the icons could only be reached with object
        navigation."""
        desktop = self._desktop()
        calls = []
        desktop.focus_list = lambda: calls.append('focus') or True
        real_take = win_shell.take_foreground
        win_shell.take_foreground = lambda hwnd: True
        try:
            desktop.focus_icons()
            wx.Yield()
            self.assertEqual(calls, ['focus', 'focus'])
        finally:
            win_shell.take_foreground = real_take
            desktop.Destroy()

    def test_the_list_gets_an_icon_focused_and_not_only_the_list(self):
        """A list view with no focused item reads as an empty container."""
        desktop = self._desktop()
        try:
            desktop.Show()
            desktop.focus_list()
            wx.Yield()
            self.assertEqual(desktop.list.GetFirstSelected(), 0)
            self.assertNotEqual(
                desktop.list.GetNextItem(-1, wx.LIST_NEXT_ALL,
                                         wx.LIST_STATE_FOCUSED), -1)
        finally:
            desktop.Hide()
            desktop.Destroy()

    def test_windows_d_shows_the_list_and_not_only_the_focus(self):
        """Shown, put back at the bottom, re-read if it changed, focused."""
        desktop = self._desktop()
        done = []
        desktop.send_to_back = lambda: done.append('back')
        desktop.focus_icons = lambda: done.append('focus') or True
        desktop.refresh = lambda: done.append('refresh')
        try:
            self.assertTrue(desktop.bring_up())
            self.assertIn('back', done)
            self.assertIn('focus', done)
            # The first call learns the folder's stamp, so it re-reads; the
            # second must not, or every Windows+D would rebuild the desktop.
            done.clear()
            desktop.bring_up()
            self.assertNotIn('refresh', done)
        finally:
            desktop.Destroy()

    def test_the_list_carries_its_name_into_msaa(self):
        """`SetName` is wx's own name and never reaches a screen reader."""
        desktop = self._desktop()
        try:
            self.assertTrue(getattr(desktop.list, '_shell_accessible', None),
                            "the desktop list has no accessible of its own")
            name, = desktop.list._shell_accessible.GetName(0)[1],
            self.assertEqual(name, _("Desktop"))
        finally:
            desktop.Destroy()

    def test_becoming_the_active_window_puts_the_keyboard_on_the_icons(self):
        desktop = self._desktop()
        calls = []
        desktop.focus_list = lambda: calls.append('focus') or True
        try:
            event = wx.ActivateEvent(wx.wxEVT_ACTIVATE, True)
            desktop._on_activate(event)
            wx.Yield()
            self.assertEqual(calls, ['focus'])
        finally:
            desktop.Destroy()


class StartMenuSearchTests(unittest.TestCase):
    """The search box behaves like the one in Windows' own Start menu."""

    def setUp(self):
        from src.shell.start_menu import XPStartMenu
        self.menu = XPStartMenu(None, shell=None)
        self.addCleanup(self.menu.Destroy)

    def test_the_menu_is_called_the_start_menu(self):
        self.assertEqual(self.menu.GetTitle(), _("Start menu"))

    def test_a_result_says_what_it_is_and_where_it_came_from(self):
        self.menu.search_field.SetValue(
            self.menu.right_list.entries[0].label[:3])
        self.assertEqual(self.menu.left_list.GetColumnCount(), 2)
        self.assertTrue(self.menu.left_list.GetItemCount())
        self.assertTrue(self.menu.left_list.GetItemText(0, 0))
        self.assertTrue(self.menu.left_list.GetItemText(0, 1),
                        "a result that does not say where it is from")

    def test_the_count_is_in_the_name_the_reader_reads(self):
        self.menu.search_field.SetValue('a')
        self.assertIn(str(self.menu.left_list.GetItemCount()),
                      self.menu.left_list.GetName())

    def test_clearing_the_box_puts_the_menu_back_in_the_column(self):
        self.menu.search_field.SetValue('a')
        self.assertTrue(self.menu.left_list.IsShown())
        self.menu.clear_search()
        self.assertTrue(self.menu.left_tree.IsShown())
        self.assertFalse(self.menu.left_list.IsShown())
        self.assertEqual(self.menu.left_tree.GetName(), _("Programs"))

    def test_the_count_is_announced_once_the_typing_stops(self):
        said = []
        from src.accessibility import messages
        real = messages.announce_search_results
        messages.announce_search_results = lambda count, label=None: \
            said.append(count)
        try:
            self.menu.search_field.SetValue('a')
            self.menu._on_announce_tick(None)
            self.assertEqual(said, [self.menu.left_list.GetItemCount()])
        finally:
            messages.announce_search_results = real

    def test_the_count_is_said_to_a_screen_reader_and_to_nobody_else(self):
        from src.accessibility import messages
        real_ta = messages._ta_speak
        real_sr = messages.is_screen_reader_running
        real_speak = messages.speak_sr_only
        spoken = []
        messages._ta_speak = lambda *args, **kwargs: False
        messages.is_screen_reader_running = lambda: False
        messages.speak_sr_only = lambda *args, **kwargs: spoken.append(args)
        try:
            self.assertFalse(messages.announce_search_results(3))
            self.assertEqual(spoken, [])
            messages.is_screen_reader_running = lambda: True
            self.assertTrue(messages.announce_search_results(3))
            self.assertEqual(len(spoken), 1)
            self.assertIn('3', spoken[0][0])
        finally:
            messages._ta_speak = real_ta
            messages.is_screen_reader_running = real_sr
            messages.speak_sr_only = real_speak


class FakeKey:
    """A key press, as the char hook reads one."""

    def __init__(self, code, alt=False, control=False, shift=False):
        self.code = code
        self.alt = alt
        self.control = control
        self.shift = shift
        self.skipped = False

    def GetKeyCode(self):
        return self.code

    def AltDown(self):
        return self.alt

    def ControlDown(self):
        return self.control

    def ShiftDown(self):
        return self.shift

    def Skip(self, skip=True):
        self.skipped = skip


class AltF4Tests(unittest.TestCase):
    """Alt+F4 anywhere in the shell means Shut Down, not a closed shell.

    The taskbar, the desktop and the Start menu are furniture: they have no
    document to close, and wx destroying one leaves the shell holding a dead
    frame - which is the crash this locks down.  The browser window is the
    one shell window Alt+F4 really closes, because it IS a window with
    something in it.
    """

    def test_the_helper_puts_the_dialog_up_once(self):
        from src.shell import shutdown_dialog
        shown = []
        real = shutdown_dialog.show_shutdown_dialog

        def fake(parent=None, default='shutdown'):
            shown.append(parent)
            # A second Alt+F4 while the dialog is up must not stack another.
            self.assertTrue(shutdown_dialog.is_shutdown_dialog_open())
            self.assertTrue(shutdown_dialog.shell_alt_f4(None))
            self.assertEqual(len(shown), 1)
            return None

        shutdown_dialog.show_shutdown_dialog = fake
        try:
            self.assertTrue(shutdown_dialog.shell_alt_f4(None))
        finally:
            shutdown_dialog.show_shutdown_dialog = real
        self.assertEqual(len(shown), 1)
        self.assertFalse(shutdown_dialog.is_shutdown_dialog_open())

    def test_every_shell_window_answers_the_key(self):
        """Not only the desktop: the bar and the menu route it too."""
        import re
        for name in ('taskbar.py', 'desktop.py', 'start_menu.py'):
            source = open(os.path.join(REPO, 'src', 'shell', name),
                          encoding='utf-8').read()
            self.assertTrue(
                re.search(r'WXK_F4.*\n?.*AltDown|AltDown.*WXK_F4', source),
                "{} does not answer Alt+F4".format(name))
            self.assertIn('shell_alt_f4', source,
                          "{} does not open the Shut Down dialog".format(name))

    def test_the_furniture_refuses_to_be_closed_by_anything_else(self):
        """A close that is not the shell's own teardown is vetoed."""
        for name in ('taskbar.py', 'desktop.py'):
            source = open(os.path.join(REPO, 'src', 'shell', name),
                          encoding='utf-8').read()
            self.assertIn('def allow_close', source)
            self.assertIn('event.Veto()', source)
        manager = open(os.path.join(REPO, 'src', 'shell', 'shell_manager.py'),
                       encoding='utf-8').read()
        self.assertIn('allow_close()', manager,
                      "the shell's own teardown must be allowed through")

    def test_the_browser_window_really_closes(self):
        from src.shell import explorer
        source = open(explorer.__file__, encoding='utf-8').read()
        self.assertIn('self.Close()', source)


class ExplorerNamespaceTests(unittest.TestCase):
    """What a place is, and what going up from one means."""

    def test_my_computer_is_the_top(self):
        from src.shell import explorer
        self.assertTrue(explorer.is_computer(explorer.COMPUTER))
        self.assertIsNone(explorer.parent_location(explorer.COMPUTER))

    def test_a_drive_goes_up_to_my_computer_not_to_a_path(self):
        from src.shell import explorer
        self.assertEqual(explorer.parent_location('C:' + os.sep),
                         explorer.COMPUTER)
        self.assertEqual(explorer.parent_location('C:'), explorer.COMPUTER)

    def test_a_folder_goes_up_one_level(self):
        from src.shell import explorer
        deep = os.path.join('C:' + os.sep, 'Users', 'somebody', 'Documents')
        self.assertEqual(explorer.parent_location(deep),
                         os.path.join('C:' + os.sep, 'Users', 'somebody'))
        self.assertEqual(
            explorer.parent_location(os.path.join('C:' + os.sep, 'Users')),
            'C:' + os.sep)

    def test_sizes_read_the_way_explorer_writes_them(self):
        from src.shell import explorer
        self.assertEqual(explorer.format_size(0), '')
        self.assertIn('KB', explorer.format_size(1))
        self.assertIn('KB', explorer.format_size(2048))
        self.assertIn('GB', explorer.format_size(3 * 1024 ** 3))

    def test_a_folder_is_listed_folders_first(self):
        import tempfile
        from src.shell import explorer
        with tempfile.TemporaryDirectory() as folder:
            os.mkdir(os.path.join(folder, 'zzz_folder'))
            open(os.path.join(folder, 'aaa.txt'), 'w').close()
            names = [entry['name']
                     for entry in explorer.list_folder(folder)]
            self.assertEqual(names, ['zzz_folder', 'aaa.txt'])

    def test_hidden_files_are_out_of_the_way_until_they_are_asked_for(self):
        import tempfile
        from src.shell import explorer
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, '.hidden'), 'w').close()
            open(os.path.join(folder, 'plain.txt'), 'w').close()
            self.assertEqual(
                [entry['name'] for entry in explorer.list_folder(folder)],
                ['plain.txt'])
            self.assertEqual(
                sorted(entry['name'] for entry
                       in explorer.list_folder(folder, show_hidden=True)),
                ['.hidden', 'plain.txt'])

    def test_my_computer_is_the_drives_windows_reports(self):
        from src.shell import explorer
        entries = explorer.list_computer()
        self.assertTrue(entries, "this machine has no drives?")
        for entry in entries:
            self.assertEqual(entry['kind'], 'drive')
            self.assertIn('(', entry['name'])


class ExplorerWindowTests(unittest.TestCase):
    """The browser as a window: its columns, its history, its status bar."""

    @classmethod
    def setUpClass(cls):
        from src.shell import explorer
        cls.explorer = explorer
        cls.frame = explorer.ExplorerFrame(None, explorer.COMPUTER)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.frame.Destroy()
        except Exception:
            pass

    def test_my_computer_has_my_computers_columns(self):
        self.frame.navigate(self.explorer.COMPUTER)
        labels = [label for label, _width in self.frame.columns()]
        self.assertEqual(len(labels), 4)
        self.assertEqual(self.frame.list.GetColumnCount(), 4)
        # A drive answers with its size and free space, not with a date.
        entry = self.frame.entries[0]
        self.assertTrue(self.frame.cell_text(entry, 2))

    def test_a_folder_has_a_folders_columns(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, 'note.txt'), 'w').write('hello')
            self.assertTrue(self.frame.navigate(folder))
            self.assertEqual(self.frame.list.GetItemCount(), 1)
            self.assertEqual(self.frame.entries[0]['name'], 'note.txt')
            self.assertIn('KB', self.frame.cell_text(self.frame.entries[0], 1))
            self.assertTrue(self.frame.cell_text(self.frame.entries[0], 3))

    def test_the_status_bar_says_how_many_and_where(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, 'a.txt'), 'w').close()
            open(os.path.join(folder, 'b.txt'), 'w').close()
            self.frame.navigate(folder)
            first, _size, where = self.frame.status_texts()
            self.assertIn('2', first)
            self.assertEqual(where, self.explorer.location_name(folder))

    def test_back_forward_and_up_walk_the_history(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            child = os.path.join(folder, 'inside')
            os.mkdir(child)
            self.frame.navigate(folder)
            self.frame.navigate(child)
            self.assertTrue(self.frame.go_back())
            self.assertEqual(os.path.normcase(str(self.frame.location)),
                             os.path.normcase(folder))
            self.assertTrue(self.frame.go_forward())
            self.assertEqual(os.path.normcase(str(self.frame.location)),
                             os.path.normcase(child))
            self.assertTrue(self.frame.go_up())
            self.assertEqual(os.path.normcase(str(self.frame.location)),
                             os.path.normcase(folder))

    def test_going_up_from_a_drive_lands_on_my_computer(self):
        self.frame.navigate('C:' + os.sep)
        self.assertTrue(self.frame.go_up())
        self.assertTrue(self.explorer.is_computer(self.frame.location))
        # And there is nowhere above it, which is where Backspace stops.
        self.assertFalse(self.frame.go_up())

    def test_the_list_is_named_after_where_it_is(self):
        """A native list view answers MSAA itself, so it is named for it."""
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            self.frame.navigate(folder)
            source = open(self.explorer.__file__, encoding='utf-8').read()
            self.assertIn('name_control(self.list', source)
            self.assertIn('name_control(self.tree', source)
            self.assertIn('name_control(self.address', source)

    def test_the_four_views_are_all_real(self):
        for view in (self.explorer.VIEW_LARGE, self.explorer.VIEW_SMALL,
                     self.explorer.VIEW_LIST, self.explorer.VIEW_DETAILS):
            self.assertTrue(self.frame.set_view(view))
            self.assertEqual(self.frame.view, view)
        self.assertFalse(self.frame.set_view('nonsense'))


class ExplorerKeyboardTests(unittest.TestCase):
    """The keys really work, and they act on what has the keyboard.

    This is the part a menu accelerator gets wrong: an accelerator fires
    wherever the focus is, so Del would delete the selected files while the
    user was typing in the address field.  The window asks first.
    """

    @classmethod
    def setUpClass(cls):
        from src.shell import explorer
        cls.explorer = explorer
        cls.frame = explorer.ExplorerFrame(None, explorer.COMPUTER)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.frame.Destroy()
        except Exception:
            pass

    def _pressed(self, code, **modifiers):
        """Press a key at the char hook and say what the window did."""
        calls = []
        frame = self.frame
        watched = ('open_selected', 'delete_selected', 'rename_selected',
                   'go_up', 'go_back', 'go_forward', 'refresh', 'paste',
                   'select_all', 'show_properties')
        originals = {name: getattr(frame, name) for name in watched}
        original_copy = frame.copy_selection
        for name in watched:
            setattr(frame, name,
                    lambda *args, _name=name, **kwargs: calls.append(_name))
        frame.copy_selection = lambda cut=False, **kwargs: calls.append(
            'cut' if cut else 'copy')
        event = FakeKey(code, **modifiers)
        try:
            frame._on_char_hook(event)
        finally:
            for name, method in originals.items():
                setattr(frame, name, method)
            frame.copy_selection = original_copy
        return calls, event

    def test_enter_delete_backspace_and_f2_all_do_something(self):
        self.frame.list.SetFocus()
        for code, expected in ((wx.WXK_RETURN, 'open_selected'),
                               (wx.WXK_NUMPAD_ENTER, 'open_selected'),
                               (wx.WXK_DELETE, 'delete_selected'),
                               (wx.WXK_F2, 'rename_selected'),
                               (wx.WXK_BACK, 'go_up'),
                               (wx.WXK_F5, 'refresh')):
            calls, event = self._pressed(code)
            self.assertEqual(calls, [expected],
                             "key {} did nothing".format(code))
            self.assertFalse(event.skipped)

    def test_the_clipboard_keys_work_on_the_files(self):
        self.frame.list.SetFocus()
        for code, expected in ((ord('C'), 'copy'), (ord('X'), 'cut'),
                               (ord('V'), 'paste'), (ord('A'), 'select_all')):
            calls, _event = self._pressed(code, control=True)
            self.assertEqual(calls, [expected])

    def test_alt_left_right_and_up_move_about(self):
        for code, expected in ((wx.WXK_LEFT, 'go_back'),
                               (wx.WXK_RIGHT, 'go_forward'),
                               (wx.WXK_UP, 'go_up')):
            calls, _event = self._pressed(code, alt=True)
            self.assertEqual(calls, [expected])

    def test_alt_enter_opens_the_properties(self):
        calls, _event = self._pressed(wx.WXK_RETURN, alt=True)
        self.assertEqual(calls, ['show_properties'])

    def test_typing_in_the_address_field_never_deletes_a_file(self):
        """The whole reason these are not menu accelerators."""
        self.frame.address.SetFocus()
        try:
            for code in (wx.WXK_DELETE, wx.WXK_F2, wx.WXK_BACK):
                calls, event = self._pressed(code)
                self.assertEqual(calls, [], "key {} acted on the files while "
                                 "the user was typing".format(code))
                self.assertTrue(event.skipped)
            # Enter in the address field goes where it says, and does not
            # open whatever happened to be selected in the list.
            went = []
            real = self.frame._on_address_enter
            self.frame._on_address_enter = lambda event=None: went.append(1)
            try:
                calls, _event = self._pressed(wx.WXK_RETURN)
            finally:
                self.frame._on_address_enter = real
            self.assertEqual(calls, [])
            self.assertEqual(went, [1])
        finally:
            self.frame.list.SetFocus()

    def test_the_commands_themselves_know_where_the_keyboard_is(self):
        """Even reached another way, a command must not act on the files."""
        self.frame.address.SetFocus()
        try:
            self.assertIsNotNone(self.frame.text_focus())
            self.assertFalse(self.frame.delete_selected())
            self.assertFalse(self.frame.rename_selected())
        finally:
            self.frame.list.SetFocus()
        self.assertIsNone(self.frame.text_focus())

    def test_alt_f4_closes_this_window_rather_than_the_computer(self):
        from src.shell import shutdown_dialog
        shown = []
        real = shutdown_dialog.show_shutdown_dialog
        shutdown_dialog.show_shutdown_dialog = lambda *a, **k: shown.append(1)
        closed = []
        real_close = self.frame.Close
        self.frame.Close = lambda *a, **k: closed.append(1)
        try:
            self.frame._on_char_hook(FakeKey(wx.WXK_F4, alt=True))
        finally:
            shutdown_dialog.show_shutdown_dialog = real
            self.frame.Close = real_close
        self.assertEqual(closed, [1])
        self.assertEqual(shown, [])


class ExplorerActionTests(unittest.TestCase):
    """The browser through the Action API, for macros and the AI."""

    def test_the_actions_are_declared(self):
        names = [name for name, *_rest in shell_actions.get_shell_actions()]
        for name in ('open_explorer', 'list_drives', 'list_folder'):
            self.assertIn(name, names)

    def test_the_drives_are_listed_with_their_free_space(self):
        answer = said(shell_actions.shell_list_drives())
        self.assertTrue(answer)
        self.assertIn('C:', answer)

    def test_a_folder_is_listed_and_a_missing_one_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, 'thing.txt'), 'w').close()
            answer = said(shell_actions.shell_list_folder(path=folder))
            self.assertIn('thing.txt', answer)
        self.assertTrue(refused(shell_actions.shell_list_folder(
            path=os.path.join(folder, 'gone'))))
        self.assertTrue(asked(shell_actions.shell_list_folder()))

    def test_my_computer_can_be_listed_by_name(self):
        answer = said(shell_actions.shell_list_folder(path='My Computer'))
        self.assertIn('C:', answer)

class ShellSoundTests(unittest.TestCase):
    """The shell's own three sounds, and the switch that silences them.

    They say what the shell is DOING - it has started, it is going away, it
    has gone somewhere - which is a different thing from the focus cues, and
    so has a switch of its own.  Nothing here is speech: the shell still
    never speaks.
    """

    def test_the_three_sounds_are_in_the_theme(self):
        from src.titan_core import sound
        from src.shell import a11y
        for name in (a11y.SOUND_STARTUP, a11y.SOUND_SHUTDOWN,
                     a11y.SOUND_NAVIGATE):
            path = sound.shell_sound_path(name)
            self.assertTrue(path, "{} is missing".format(name))
            self.assertTrue(os.path.exists(path))
            # In the theme's own `shell` folder, not loose in the theme.
            self.assertEqual(os.path.basename(os.path.dirname(path)), 'shell')

    def test_a_theme_without_them_still_hears_the_shell(self):
        """The sounds belong to the feature, so the default set answers."""
        from src.titan_core import sound
        from src.shell import a11y
        real = sound.current_theme
        sound.current_theme = 'a theme that does not exist'
        try:
            path = sound.shell_sound_path(a11y.SOUND_STARTUP)
        finally:
            sound.current_theme = real
        self.assertTrue(path)
        self.assertIn('default', path)

    def test_the_switch_silences_them(self):
        from src.shell import a11y
        played = []
        real_play = a11y.play_shell_sound
        real_setting = a11y.shell_setting
        a11y.play_shell_sound = lambda *args, **kwargs: played.append(args)
        a11y.shell_setting = lambda key, default: (
            False if key == 'shell_sounds' else real_setting(key, default))
        try:
            self.assertFalse(a11y.sounds_enabled())
            self.assertFalse(a11y.shell_sound(a11y.SOUND_STARTUP))
            self.assertEqual(played, [])
            a11y.shell_setting = lambda key, default: (
                True if key == 'shell_sounds' else real_setting(key, default))
            a11y.shell_sound(a11y.SOUND_STARTUP)
            self.assertEqual(len(played), 1)
        finally:
            a11y.play_shell_sound = real_play
            a11y.shell_setting = real_setting

    def test_the_shell_says_when_it_goes_away_and_waits_for_it(self):
        """Titan may exit the moment stop() returns, so it is waited out."""
        from src.shell import shell_manager
        played = []
        real = shell_manager.shell_sound
        shell_manager.shell_sound = lambda name, **kwargs: played.append(
            (name, kwargs.get('wait', False)))
        try:
            shell = shell_manager.TitanShell(parent=None)
            shell.stop()
            self.assertEqual(played, [], "a shell that never ran said goodbye")
            shell._running = True
            shell.stop(wait=True)
            self.assertEqual(played,
                             [(shell_manager.SOUND_SHUTDOWN, True)])
            # Turning the shell off from the settings still says goodbye,
            # but does not hold the dialog for the length of the clip.
            del played[:]
            shell._running = True
            shell.stop()
            self.assertEqual(played,
                             [(shell_manager.SOUND_SHUTDOWN, False)])
        finally:
            shell_manager.shell_sound = real

    def test_the_shell_says_when_it_has_started(self):
        from src.shell import shell_manager
        source = open(shell_manager.__file__, encoding='utf-8').read()
        self.assertIn('shell_sound(SOUND_STARTUP)', source)
        # And only once everything is really up.
        self.assertLess(source.index('self._running = True'),
                        source.index('shell_sound(SOUND_STARTUP)'))

    def test_going_to_a_folder_sounds_like_explorer(self):
        import tempfile
        from src.shell import explorer
        played = []
        real = explorer.shell_sound
        explorer.shell_sound = lambda name, **kwargs: played.append(name)
        frame = None
        try:
            frame = explorer.ExplorerFrame(None, explorer.COMPUTER)
            del played[:]
            with tempfile.TemporaryDirectory() as folder:
                os.mkdir(os.path.join(folder, 'inside'))
                frame.navigate(folder)
                frame.navigate(os.path.join(folder, 'inside'))
                frame.go_back()
                frame.go_up()
            self.assertEqual(played, [explorer.SOUND_NAVIGATE] * 4)
        finally:
            explorer.shell_sound = real
            if frame is not None:
                frame.Destroy()

    def test_the_sound_is_reachable_as_a_setting(self):
        answer = said(shell_actions.shell_list_settings())
        self.assertIn('shell sounds', answer)


class ShellSettingsPanelTests(unittest.TestCase):
    """The shell settings are grouped, and the groups are real ones.

    A `wx.StaticBox` is a grouping Windows itself knows about, so a screen
    reader says which group the keyboard has entered - which is the whole
    point of grouping twenty checkboxes rather than listing them.
    """

    def setUp(self):
        self.source = open(os.path.join(REPO, 'src', 'ui', 'settingsgui.py'),
                           encoding='utf-8').read()
        start = self.source.index('def InitTitanShellPanel')
        self.panel_source = self.source[start:
                                        self.source.index(
                                            'def InitSystemMonitorPanel')]

    def test_the_settings_are_in_static_box_groups(self):
        self.assertIn('wx.StaticBoxSizer', self.panel_source)
        for title in ('The system interface', 'The desktop', 'The taskbar',
                      'Sounds', 'Shortcuts Titan takes over'):
            self.assertIn(title, self.panel_source,
                          "no group called {}".format(title))

    def test_a_grouped_control_belongs_to_its_box(self):
        """wx wants the box itself as the parent, or the group is a drawing."""
        self.assertIn('box.GetStaticBox()', self.panel_source)
        self.assertNotIn('wx.CheckBox(panel', self.panel_source)

    def test_the_sound_switch_is_there(self):
        self.assertIn("'shell_sounds'", self.panel_source)
        self.assertIn("'focus_cues'", self.panel_source)

class ExitTitanTests(unittest.TestCase):
    """"Turn off TCE" is not a second kind of exit.

    Every face of Titan already has a way out that asks first when the user
    asked to be asked (`shutdown_question`) and then runs the one teardown -
    hooks off, shell stopped, appbar unregistered, Explorer's taskbar back.
    The Shut Down dialog's own entry hands the exit to that, and the shell
    says goodbye out loud on the way.
    """

    class FakeMain(wx.Frame):
        """A stand-in for Titan's main window: it has `shutdown_app`."""

        def __init__(self):
            super().__init__(None, title='FakeTitanMain')
            self.closed = False
            self.shut_down = False

        def Close(self, force=False):
            self.closed = True
            return True

        def shutdown_app(self):
            self.shut_down = True

    class FakeKlango(wx.Frame):
        """Klango mode: it does the asking itself, in `exit_program`."""

        def __init__(self):
            super().__init__(None, title='FakeKlango')
            self.exited = False

        def exit_program(self):
            self.exited = True

    def test_the_main_window_is_closed_the_way_the_menu_closes_it(self):
        from src.shell import shutdown_dialog
        frame = self.FakeMain()
        try:
            self.assertIs(shutdown_dialog.titan_main_window(), frame)
            self.assertTrue(shutdown_dialog.exit_titan())
            wx.Yield()
            # Close(), so `main.py`'s EVT_CLOSE binding does the asking -
            # rather than shutdown_app(), which would skip the question.
            self.assertTrue(frame.closed)
            self.assertFalse(frame.shut_down)
        finally:
            frame.Destroy()
            wx.Yield()

    def test_klango_mode_exits_through_its_own_way_out(self):
        from src.shell import shutdown_dialog
        frame = self.FakeKlango()
        try:
            self.assertTrue(shutdown_dialog.exit_titan())
            wx.Yield()
            self.assertTrue(frame.exited)
        finally:
            frame.Destroy()
            wx.Yield()

    def test_the_shells_own_windows_are_never_taken_for_the_main_one(self):
        """They refuse to close, so closing one would put the dialog up again."""
        from src.shell import explorer, shutdown_dialog
        browser = explorer.ExplorerFrame(None, explorer.COMPUTER)
        frame = self.FakeMain()
        try:
            self.assertIs(shutdown_dialog.titan_main_window(), frame)
        finally:
            frame.Destroy()
            browser.Destroy()
            wx.Yield()

    def test_turning_tce_off_is_one_of_the_dialogs_own_entries(self):
        from src.shell import shutdown_dialog
        identifiers = [identifier for identifier, _label, _description
                       in shutdown_dialog.shutdown_actions()]
        self.assertIn('exit_titan', identifiers)

    def test_the_shell_is_stopped_before_titans_own_goodbye_sound(self):
        """The logoff sound comes first, as it does on Windows."""
        for path in (os.path.join(REPO, 'src', 'ui', 'gui.py'),
                     os.path.join(REPO, 'src', 'system', 'klangomode.py')):
            source = open(path, encoding='utf-8').read()
            self.assertIn('stop_shell(quiet=quick_start, wait=True)', source,
                          "{} does not stop the shell".format(path))
            self.assertLess(source.index('stop_shell(quiet=quick_start'),
                            source.index('play_shutdown_sound()'),
                            "{} says goodbye before logging out".format(path))

    def test_a_quiet_stop_says_nothing(self):
        """Quick start's quick exit, and an exit that already said it."""
        from src.shell import shell_manager
        played = []
        real = shell_manager.shell_sound
        shell_manager.shell_sound = lambda name, **kwargs: played.append(name)
        try:
            shell = shell_manager.TitanShell(parent=None)
            shell._running = True
            shell.stop(quiet=True)
            self.assertEqual(played, [])
            shell._running = True
            shell.stop()
            self.assertEqual(played, [shell_manager.SOUND_SHUTDOWN])
        finally:
            shell_manager.shell_sound = real

if __name__ == '__main__':
    unittest.main(verbosity=2)
