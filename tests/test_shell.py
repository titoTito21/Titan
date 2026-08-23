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
15. Starting the shell keeps the GUI thread free: the bar is docked before
    anything is read into it, the desktop's icons and the notification area
    are read afterwards, the user's startup programs run on a thread, and
    nothing the shell asks another program can be held by a hung one.
16. The strip changes hands off the GUI thread and in order - Explorer's bar
    gives it up, then ours claims it - because those two calls into Explorer
    take seconds of the whole session's time, and the shell must spend them
    answering Windows rather than queueing behind it.
17. A modifier the user has let go of is not held.  The shell must not hand
    the `keyboard` library a suppressed HOTKEY (that switches on a state
    machine which holds every modifier back and replays it), and it must not
    believe a Shift that only the input queue remembers - taking the
    foreground merges this thread's queue with another program's, and a
    Shift latched there made Tab move backwards for ever.

Run directly: python tests/test_shell.py
"""

import os
import re
import sys
import threading
import types
import time
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
        # The whole method, not the first N characters of it: a slice
        # makes the test fail when something is ADDED to the panel.
        method = source.split('def InitTitanShellPanel')[1]
        panel = method.split('\n    def ')[0]
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


def _is_addon_payload(payload):
    """Whether a menu entry was put there by a shell add-on."""
    return isinstance(payload, tuple) and payload[:1] == ('__addon__',)


def _bar_with(windows=(), icons=(), launchers=('Chrome', 'Editor')):
    """A taskbar frame carrying a made-up window list, tray and band.

    The quick launch band reads a real folder, so a test that did not say
    what is in it would pass or fail depending on whose machine it ran on.
    The shell add-ons are the same kind of dependency - one of them puts a
    control of its own in the notification area, which is a fifth thing in
    that group and a wider strip - so this bar carries Titan's own furniture
    and nothing else. What an add-on puts there is tested in
    tests/test_shell_addons.py.
    """
    from src.shell.shell_manager import TitanShell
    from src.shell import taskbar as taskbar_module

    real_items = taskbar_module.quick_launch_items
    taskbar_module.quick_launch_items = lambda: [
        {'name': name, 'path': 'C:/' + name + '.lnk'} for name in launchers]
    # The band is also a SETTING, and one this machine's user may well have
    # turned off - which is not something a test about the bar's groups
    # should depend on.  It is answered for, for as long as the bar is being
    # built, exactly as the folder is.
    real_setting = taskbar_module.shell_setting

    def setting(name, default=None):
        if name == 'show_quick_launch':
            return True
        return real_setting(name, default)

    taskbar_module.shell_setting = setting
    real_collect = taskbar_module.shell_addons.collect
    taskbar_module.shell_addons.collect = (
        lambda surface, hook, *args, **kwargs:
        [] if surface == 'taskbar' else real_collect(surface, hook,
                                                     *args, **kwargs))
    try:
        bar = taskbar_module.TaskbarFrame(TitanShell())
        bar.shows_quick_launch = lambda: True
        # And it stays that way through every later refresh of the tray.
        bar._build_addon_bands = lambda: []
        bar._addon_bands = []
    finally:
        taskbar_module.quick_launch_items = real_items
        taskbar_module.shell_setting = real_setting
        taskbar_module.shell_addons.collect = real_collect
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

    def test_the_shell_says_when_it_goes_away_without_waiting(self):
        """The goodbye is heard on the way out, not waited through.

        It used to hold its caller for the length of the clip, so that a
        sound still in the mixer when the process went was not lost.  The
        other side of that is a program that will not close while a sound
        finishes, which is worse - and Titan's own shutdown takes long
        enough that most of the clip is heard anyway.
        """
        from src.shell import shell_manager
        played = []
        real = shell_manager.shell_sound
        shell_manager.shell_sound = lambda name, **kwargs: played.append(
            (name, kwargs))
        try:
            shell = shell_manager.TitanShell(parent=None)
            shell.stop()
            self.assertEqual(played, [], "a shell that never ran said goodbye")
            shell._running = True
            shell.stop()
            self.assertEqual(played, [(shell_manager.SOUND_SHUTDOWN, {})],
                             "the goodbye still asks to be waited for")
        finally:
            shell_manager.shell_sound = real

    def test_nothing_can_ask_the_shell_sounds_to_block(self):
        from src.titan_core import sound
        with open(sound.__file__, encoding='utf-8') as handle:
            source = handle.read()
        body = source[source.index('def play_shell_sound'):
                      source.index('def play_connecting_sound')]
        self.assertNotIn('time.sleep', body,
                         "the shell's goodbye still holds up the exit")
        signature = body.splitlines()[0]
        self.assertNotIn('wait', signature,
                         "something can still ask it to block")

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
            self.assertIn('stop_shell(quiet=quick_start)', source,
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

class ShellStartupSpeedTests(unittest.TestCase):
    """Starting the shell must not stop the machine.

    A shell is not an ordinary program: with the appbar registered and the
    shell hook installed, every broadcast Windows sends to top-level windows
    goes through this process, so a GUI thread busy for half a second is
    half a second of a system that feels stuck - not just a slow Titan.
    Everything slow therefore happens off that thread, and these tests lock
    down which things those are.
    """

    class FakeShell:
        parent = None

        def __init__(self):
            self.desktop = self.taskbar = self.start_menu = None

        def toggle_start_menu(self):
            pass

        def own_hwnds(self):
            return ()

        def taskbar_height(self):
            return 30

    def test_the_desktop_can_be_put_up_without_reading_it(self):
        """`defer` is what the shell starts the desktop with."""
        import time
        from src.shell.desktop import DesktopFrame
        started = time.perf_counter()
        desktop = DesktopFrame(self.FakeShell(), defer=True)
        elapsed = (time.perf_counter() - started) * 1000
        try:
            # The window exists at once; the icons arrive on their own.
            self.assertLess(elapsed, 250,
                            "putting the desktop up took {:.0f} ms".format(
                                elapsed))
            deadline = time.time() + 20
            while time.time() < deadline and not desktop.items:
                wx.Yield()
                time.sleep(0.02)
            self.assertTrue(desktop.items, "the icons never arrived")
            self.assertEqual(desktop.list.GetItemCount(), len(desktop.items))
        finally:
            desktop.Destroy()
            wx.Yield()

    def test_an_icon_read_once_is_not_read_again(self):
        """A refresh used to be half a second of Windows shell calls."""
        from src.shell import desktop as desktop_module
        from src.shell.desktop import DesktopFrame
        desktop = DesktopFrame(self.FakeShell())
        asked = []
        real = desktop_module.win_shell.file_icon_handle
        desktop_module.win_shell.file_icon_handle = (
            lambda path, large=True: asked.append(path) or real(path, large))
        try:
            desktop.refresh()
            self.assertEqual(asked, [], "the icons were read a second time")
        finally:
            desktop_module.win_shell.file_icon_handle = real
            desktop.Destroy()
            wx.Yield()

    def test_a_renamed_item_gets_its_icon_read_again(self):
        """The cache is keyed on the file, not merely on its name."""
        from src.shell.desktop import DesktopFrame
        desktop = DesktopFrame(self.FakeShell())
        try:
            self.assertIsNone(desktop._cached_bitmap(
                os.path.join(REPO, 'no such file.txt')))
            path = os.path.join(REPO, 'CLAUDE.md')
            bitmap = desktop._bitmap_for(path)
            self.assertIsNotNone(bitmap)
            self.assertIs(desktop._cached_bitmap(path), bitmap)
        finally:
            desktop.Destroy()
            wx.Yield()

    def test_the_type_name_is_read_only_when_something_wants_it(self):
        """Another shell call per item, and the desktop shows none of them."""
        from src.shell.desktop import DesktopFrame
        desktop = DesktopFrame(self.FakeShell())
        try:
            if not desktop.items:
                self.skipTest("this desktop is empty")
            self.assertEqual(desktop.items[0]['type'], '')
            self.assertTrue(desktop.item_type(desktop.items[0]))
        finally:
            desktop.Destroy()
            wx.Yield()

    def test_the_bar_is_up_before_anything_is_read_into_it(self):
        from src.shell import shell_manager
        source = open(shell_manager.__file__, encoding='utf-8').read()
        start = source.index('    def start(self):')
        body = source[start:source.index('    def _start_startup_items')]
        self.assertLess(body.index('TaskbarFrame(self'),
                        body.index('DesktopFrame(self'),
                        "the desktop is built before the bar is docked")
        self.assertIn('defer=True', body,
                      "the desktop is read on the GUI thread at startup")
        self.assertIn('self._start_startup_items()', body)

    def test_the_users_startup_programs_run_off_the_gui_thread(self):
        """`ShellExecute` on a program that opens a window takes seconds."""
        from src.shell import shell_manager
        shell = shell_manager.TitanShell(parent=None)
        ran = []
        real = shell_manager.win_shell.run_startup_items
        shell_manager.win_shell.run_startup_items = lambda: ran.append(
            threading.current_thread()) or []
        try:
            thread = shell._start_startup_items(delay=0.05)
            self.assertIsNot(thread, threading.current_thread())
            thread.join(timeout=10)
            self.assertEqual(len(ran), 1)
            self.assertIsNot(ran[0], threading.main_thread())
        finally:
            shell_manager.win_shell.run_startup_items = real

    def test_the_notification_area_is_read_after_the_bar_is_shown(self):
        from src.shell import taskbar as taskbar_module
        source = open(taskbar_module.__file__, encoding='utf-8').read()
        dock = source[source.index('    def dock(self, after=None):'):
                      source.index('    def register_appbar')]
        # Deferred through `src.shell.deferred`, which drops the call if the
        # bar has gone by the time it fires - never `wx.CallAfter` straight.
        self.assertIn('call_after(self, self._first_tray_read)', dock)
        self.assertNotIn('self.refresh_tray()', dock)

    def test_the_appbar_is_claimed_off_the_gui_thread(self):
        """ABM_SETSTATE and ABM_NEW measured 2.4 s and 0.8 s here."""
        from src.shell import shell_manager, taskbar as taskbar_module
        bar = open(taskbar_module.__file__, encoding='utf-8').read()
        dock = bar[bar.index('    def dock(self, after=None):'):
                   bar.index('    def _appbar_ready')]
        self.assertNotIn('appbar.register()', dock.split('def work')[0])
        self.assertIn('threading.Thread', bar[bar.index('def register_appbar'):
                                              bar.index('def _appbar_ready')])
        manager = open(shell_manager.__file__, encoding='utf-8').read()
        start = manager[manager.index('    def start(self):'):
                        manager.index('    def _prebuild_start_menu')]
        self.assertIn('threading.Thread', start,
                      "Explorer's bar is still hidden on the GUI thread")
        self.assertIn('dock(after=hidden)', start,
                      "the appbar no longer waits for Explorer's bar to go")

    def test_the_shell_never_sends_a_message_a_hung_program_can_hold(self):
        """A hung window must not be able to freeze the whole taskbar."""
        from src.shell import win_shell
        source = open(win_shell.__file__, encoding='utf-8').read()
        icon = source[source.index('def window_icon_handle'):
                      source.index('def file_display_name')]
        self.assertNotIn('SendMessageW', icon)
        self.assertIn('send_message_timeout', icon)
        # And it really answers - about this very process's own window.
        frame = wx.Frame(None, title='TimeoutProbe')
        try:
            handle = win_shell.window_icon_handle(frame.GetHandle())
            self.assertIsInstance(handle, int)
        finally:
            frame.Destroy()
            wx.Yield()

    def test_a_window_with_no_icon_is_not_asked_on_every_poll(self):
        from src.shell.taskbar import TaskButton
        self.assertTrue(getattr(TaskButton, 'ICON_RETRY_SECONDS', 0) >= 10)
        source = open(os.path.join(REPO, 'src', 'shell', 'taskbar.py'),
                      encoding='utf-8').read()
        update = source[source.index('    def update(self, window):'):
                        source.index('    def middle_activate')]
        self.assertIn('ICON_RETRY_SECONDS', update)

class ExplorerHandoverTests(unittest.TestCase):
    """The strip changes hands without the shell sitting inside Windows.

    Measured on this machine: `ABM_SETSTATE` (Explorer's bar to auto-hide)
    2416 ms, `ABM_NEW` (ours registered) 849 ms, and a bare wx application
    with no Titan shell at all stalls 2407 ms while the first of those is
    happening - so the cost is Windows moving the work area and telling
    every window about it, not anything here.  What Titan controls is that
    it happens on a worker, after its own windows are up, and not at all
    when Explorer's bar is already where it is being put.
    """

    def test_the_state_is_not_set_when_it_is_already_that(self):
        """The one call that costs two and a half seconds."""
        from src.shell import win_shell
        source = open(win_shell.__file__, encoding='utf-8').read()
        body = source[source.index('def set_explorer_taskbar_reserved'):
                      source.index('def set_explorer_taskbar_visible')]
        self.assertIn('ABM_GETSTATE', body)
        self.assertLess(body.index('ABM_GETSTATE'), body.index('ABM_SETSTATE'),
                        "the state is set before it is looked at")

    def test_explorers_bar_goes_after_the_shells_windows_are_up(self):
        from src.shell import shell_manager
        source = open(shell_manager.__file__, encoding='utf-8').read()
        start = source[source.index('    def start(self):'):
                       source.index('    def _claim_the_strip')]
        self.assertLess(start.index('self._running = True'),
                        start.index('self._claim_the_strip(hidden)'),
                        "the shell waits for Windows before it is running")
        self.assertLess(start.index('DesktopFrame(self'),
                        start.index('self._claim_the_strip(hidden)'))

    def test_the_two_are_chained_rather_than_raced(self):
        """Ours must not be registered while Explorer's still owns the strip."""
        from src.shell import shell_manager, taskbar as taskbar_module
        manager = open(shell_manager.__file__, encoding='utf-8').read()
        self.assertIn('threading.Event()', manager)
        self.assertIn('dock(after=hidden)', manager)
        bar = open(taskbar_module.__file__, encoding='utf-8').read()
        worker = bar[bar.index('def register_appbar'):
                     bar.index('def _appbar_ready')]
        self.assertIn('after.wait(', worker,
                      "the appbar does not wait for Explorer's bar to go")

    def test_the_taskbar_is_given_back_even_if_the_worker_was_overtaken(self):
        """A stop that beats the hiding worker must still restore it."""
        from src.shell import shell_manager
        source = open(shell_manager.__file__, encoding='utf-8').read()
        stop = source[source.index('    def stop(self, quiet=False'):
                      source.index('    def is_running')]
        self.assertIn("shell_setting('hide_system_taskbar', True)", stop)

    def test_an_empty_notification_area_is_taken_for_not_yet(self):
        """Explorer answers nothing at all while it is re-laying out."""
        from src.shell import taskbar as taskbar_module
        source = open(taskbar_module.__file__, encoding='utf-8').read()
        read = source[source.index('    def _first_tray_read'):
                      source.index('    def refresh_tray')]
        self.assertIn('attempt', read)
        self.assertIn('call_later(', read)

    def test_the_start_menu_is_built_before_it_is_asked_for(self):
        """150 ms, and the moment it costs them is the Windows key."""
        from src.shell import shell_manager
        source = open(shell_manager.__file__, encoding='utf-8').read()
        self.assertIn('_prebuild_start_menu', source)
        body = source[source.index('    def _prebuild_start_menu'):
                      source.index('    def _start_startup_items')]
        self.assertIn('prefetch()', body,
                      "the slow lists are not warmed with it")

class WindowsKeyStateTests(unittest.TestCase):
    """The shortcuts must not be killable by one key event going missing.

    The Windows key opened WINDOWS' Start menu and no Titan shortcut fired
    at all, until Titan was restarted.  The cause was not the shell: the
    hooks asked `keyboard.is_pressed('ctrl')`, which answers out of a table
    the library fills from the events its own hook saw - and the lock
    screen (Windows+L is one of these shortcuts), Ctrl+Alt+Del and a UAC
    prompt all take the key UP on a desktop no hook of ours runs on.  One
    such Control left "held" made every Windows key press a passthrough for
    the rest of the session.

    The two keys are asked about in opposite ways, and that is the point:
    Control is let through, so Windows knows about it; the Windows key is
    SUPPRESSED, so Windows never sees it and only these hooks can say
    whether it is held.
    """

    def _manager(self):
        from src.titan_core import tce_system
        return tce_system, tce_system.SystemHooksManager()

    def _source(self, module, start, end):
        with open(module.__file__, encoding='utf-8') as handle:
            source = handle.read()
        return source[source.index(start):source.index(end)]

    def test_control_is_asked_of_windows_and_not_of_the_library(self):
        from src.titan_core import tce_system
        handler = self._source(tce_system, '    def _on_win_key',
                               '    def _on_ctrl_key')
        self.assertNotIn("keyboard.is_pressed('ctrl')", handler,
                         "a table that has missed one key up is believed again")
        self.assertIn('_key_physically_down(VK_CONTROL)', handler)

    def test_a_held_windows_key_is_never_asked_of_windows(self):
        """A suppressed key does not exist as far as Windows is concerned.

        Measured: a key blocked in a low-level hook never reaches the
        system, so `GetAsyncKeyState` reports the Windows key UP the whole
        time the user is holding it - and Titan blocks that key.  Asking
        Windows here made every Windows+<key> shortcut do nothing at all.
        """
        from src.titan_core import tce_system
        held = self._source(tce_system, '    def _windows_key_held',
                            '    def _on_win_key')
        self.assertNotIn('_key_physically_down', held,
                         "the held Windows key is being asked of Windows, "
                         "which cannot see a key Titan suppresses")

    def test_the_key_counts_as_held_while_it_is_being_used(self):
        _tce, manager = self._manager()
        manager._win_down = True
        manager._win_event_at = time.monotonic()
        self.assertTrue(manager._windows_key_held())

    def test_a_stale_held_flag_is_thrown_away(self):
        """A key up that never arrived must not fire shortcuts for ever."""
        tce_system, manager = self._manager()
        manager._win_down = True
        manager._win_passthrough = True
        manager._win_event_at = (time.monotonic()
                                 - tce_system._WIN_HELD_STALE - 1)
        self.assertFalse(manager._windows_key_held(),
                         "a press nothing has refreshed is still believed")
        self.assertFalse(manager._win_passthrough,
                         "the passthrough survived the key it belonged to")
        self.assertFalse(manager._win_down)

    def test_a_binding_fires_only_while_the_key_is_really_held(self):
        """Both ways round: it works when held, and not when merely stale."""
        import keyboard
        tce_system, manager = self._manager()
        fired = []
        manager._handle_show_desktop = lambda: fired.append(True)
        hook = manager._make_binding_hook('show_desktop')

        class Event:
            event_type = keyboard.KEY_DOWN

        # Held: the key is Titan's, so it is swallowed and the shortcut runs.
        manager._win_down = True
        manager._win_event_at = time.monotonic()
        self.assertFalse(hook(Event()),
                         "Windows+D was handed to Windows instead of running")

        # Stale: nothing has refreshed the press, so "d" is just a letter.
        fired.clear()
        manager._win_down = True
        manager._win_event_at = (time.monotonic()
                                 - tce_system._WIN_HELD_STALE - 1)
        self.assertTrue(hook(Event()), "an ordinary letter was swallowed")
        self.assertEqual(fired, [])

    def test_a_new_press_after_a_lost_release_starts_over(self):
        """Auto-repeat is not a new press; a press 1.5 s later is."""
        from src.titan_core import tce_system
        handler = self._source(tce_system, '    def _on_win_key',
                               '    def _on_ctrl_key')
        self.assertIn('_WIN_REPEAT_GAP', handler)
        self.assertGreaterEqual(tce_system._WIN_REPEAT_GAP, 1.0,
                                "Windows' own repeat delay reaches one second")


class WindowSwitcherKeyTests(unittest.TestCase):
    """Titan's function keys are Titan's only while Titan is an application.

    With the shell up, Titan IS the desktop and the keys have Windows'
    meanings: F4 is the file browser's address band, and switching windows
    is what the taskbar and Alt+Tab are for.  Windows+W and Windows+F2
    still open Titan's own switcher, so nothing is taken away.
    """

    def _with_shell(self, running):
        from src.shell import shell_manager
        from src.ui.gui import shell_owns_the_keyboard
        original = shell_manager.is_shell_running
        shell_manager.is_shell_running = lambda: running
        try:
            return shell_owns_the_keyboard()
        finally:
            shell_manager.is_shell_running = original

    def test_the_shell_takes_the_key(self):
        self.assertTrue(self._with_shell(True))

    def test_without_the_shell_it_is_still_titan_s(self):
        self.assertFalse(self._with_shell(False))

    def test_f4_asks_before_it_switches(self):
        from src.ui import gui as gui_module
        with open(gui_module.__file__, encoding='utf-8') as handle:
            source = handle.read()
        body = source[source.index('        # Handle F4 (Switch To)'):]
        body = body[:body.index('        # Handle Alt+F4')]
        self.assertLess(body.index('shell_owns_the_keyboard'),
                        body.index('on_show_window_switcher'),
                        "F4 switches windows before asking whose key it is")

    def test_klango_asks_the_same_question(self):
        """Both of its key handlers - the wx one and the pygame one."""
        from src.system import klangomode
        with open(klangomode.__file__, encoding='utf-8') as handle:
            lines = handle.read().splitlines()
        blocks = 0
        for position, line in enumerate(lines):
            if '# F4 opens window switcher' not in line:
                continue
            blocks += 1
            block = ' '.join(lines[position:position + 14])
            self.assertIn('is_shell_running', block,
                          "an F4 handler that never asks whose key it is")
            self.assertLess(block.index('is_shell_running'),
                            block.index('self.open_window_switcher()'))
        self.assertEqual(blocks, 2, "Klango mode has two F4 handlers")

    def test_the_global_f4_hotkey_stands_aside_too(self):
        """The route that was still firing in the shell's own windows.

        F4 is not only a key `on_key_down` sees: `gui.py` registers a
        GLOBAL hotkey through the keyboard library that fires whenever any
        TCE window is in the foreground - and the shell's desktop, taskbar,
        Start menu and file browser are all TCE windows.  Gating the key
        handler did nothing for it.
        """
        from src.ui import gui as gui_module
        with open(gui_module.__file__, encoding='utf-8') as handle:
            source = handle.read()
        body = source[source.index('    def _global_f4_handler'):
                      source.index('    def _unregister_global_f2_hotkey')]
        self.assertIn('shell_owns_the_keyboard()', body,
                      "the global F4 hotkey still opens the switcher "
                      "inside the shell")
        self.assertLess(body.index('shell_owns_the_keyboard'),
                        body.index('show_window_switcher'))

    def test_the_browser_keeps_f4_for_the_address_band(self):
        """Windows' own meaning of the key, which is the point of all this."""
        from src.shell import explorer
        with open(explorer.__file__, encoding='utf-8') as handle:
            source = handle.read()
        hook = source[source.index('    def _on_char_hook'):
                      source.index('    def panes(self)')]
        self.assertIn('self.address.SetFocus()', hook)


class ShellPanTests(unittest.TestCase):
    """The shell says -1..1; the mixer takes 0..1. Somebody has to convert.

    Nobody did, so `shell_sound`'s own default of 0.0 - the CENTRE in the
    shell's units - was hard left in the mixer's, and every shell sound came
    out of the left speaker alone.  The taskbar's focus cues had it worse:
    the whole left half of the screen clamped to hard left, so only the
    right half of the stereo image was ever used.  This is the same bug the
    Titan Script `play` statement had.
    """

    def test_the_centre_is_the_centre(self):
        from src.shell.a11y import mixer_pan
        self.assertAlmostEqual(mixer_pan(0.0), 0.5)

    def test_the_ends_are_the_ends(self):
        from src.shell.a11y import mixer_pan
        self.assertAlmostEqual(mixer_pan(-1.0), 0.0)
        self.assertAlmostEqual(mixer_pan(1.0), 1.0)

    def test_nothing_lands_outside_the_image(self):
        from src.shell.a11y import mixer_pan
        for position in (-9.0, 9.0, 'nonsense', None):
            self.assertTrue(0.0 <= mixer_pan(position) <= 1.0)

    def test_the_left_half_of_the_screen_is_not_all_hard_left(self):
        """What made the cues unusable: -1..0 all clamped to 0.0."""
        from src.shell.a11y import mixer_pan
        self.assertLess(mixer_pan(-1.0), mixer_pan(-0.5))
        self.assertLess(mixer_pan(-0.5), mixer_pan(0.0))

    def test_a_shell_sound_has_no_position_at_all(self):
        """Started, stopped, navigated: they happen to the whole desktop.

        And an unpanned sound is the only one at full volume in both
        channels - `sound.py`'s pan law is linear, so dead centre is half
        in each.
        """
        from src.shell import a11y
        asked = {}

        def fake(name, pan=None, wait=False):
            asked['pan'] = pan
            return True

        original = a11y.play_shell_sound
        enabled = a11y.sounds_enabled
        a11y.play_shell_sound = fake
        a11y.sounds_enabled = lambda: True
        try:
            a11y.shell_sound(a11y.SOUND_STARTUP)
            self.assertIsNone(asked['pan'], "the fanfare is being panned")
            a11y.shell_sound(a11y.SOUND_NAVIGATE, position=-1.0)
            self.assertAlmostEqual(asked['pan'], 0.0,
                                   msg="a position that IS given is ignored")
        finally:
            a11y.play_shell_sound = original
            a11y.sounds_enabled = enabled


class StartMenuIdentityTests(unittest.TestCase):
    """The menu says what it is by being CALLED it, not by talking.

    It opens straight onto a control, so the user needs to hear where that
    control is - but a window that has a title is already something every
    screen reader reads on entering it (Titan Access from its context
    presenter, NVDA from the foreground change).  Saying it from here as
    well was a second copy of the title, and one that had to be protected
    from being cut off, which meant holding the keyboard back from the
    window the user had just opened.

    What is left is the part that was really broken: the keyboard must be
    handed over exactly ONCE.  wxWidgets answers WM_ACTIVATE by focusing
    the FRAME, so a focus set before the window has finished becoming
    active is undone and then put back - two focus events, which a reader
    reads as the control twice.
    """

    def _source(self, module, start, end):
        with open(module.__file__, encoding='utf-8') as handle:
            source = handle.read()
        return source[source.index(start):source.index(end)]

    def test_the_window_is_called_the_start_menu(self):
        """Its own title is the whole of what identifies it."""
        from src.ui import classic_start_menu
        with open(classic_start_menu.__file__, encoding='utf-8') as handle:
            source = handle.read()
        self.assertIn('title=_("Start menu")', source)

    def test_the_menu_says_nothing_itself(self):
        for module_name, path in (
                ('start menu', 'src/shell/start_menu.py'),
                ('classic start menu', 'src/ui/classic_start_menu.py')):
            with open(path, encoding='utf-8') as handle:
                source = handle.read()
            self.assertNotIn('announce_shell_window', source, module_name)
            self.assertNotIn('speak_sr_only', source, module_name)

    def test_the_keyboard_is_handed_over_once(self):
        from src.shell import start_menu
        body = self._source(start_menu, '    def _hand_over_focus',
                            '    def focus_now')
        self.assertIn('if not self._focus_pending:', body,
                      "the hand-over can run more than once")
        self.assertIn('self._focus_pending = False', body)

    def test_the_activation_is_what_hands_it_over(self):
        from src.shell import start_menu
        body = self._source(start_menu, '    def show_menu',
                            '    def _hand_over_focus')
        self.assertNotIn('wx.CallAfter(self._focus_menu)', body,
                         "the focus is set without waiting for the activation")
        self.assertIn('FOCUS_FALLBACK_MS', body,
                      "nothing focuses the menu if no activation arrives")

    def test_the_focus_is_claimed_before_the_window_is_shown(self):
        from src.shell import start_menu
        body = self._source(start_menu, '    def show_menu',
                            '    def _hand_over_focus')
        self.assertLess(body.index('self._focus_pending = True'),
                        body.index('self.Show()'),
                        "the activation gets in before the flag is set")

    def test_focusing_what_is_already_focused_is_not_done_twice(self):
        """The last way a second focus event could still be fired."""
        from src.shell import start_menu
        body = self._source(start_menu, '    def focus_now',
                            '    def on_activate')
        self.assertIn('FindFocus() is not column', body)

    def test_an_activation_that_changes_nothing_is_ignored(self):
        from src.shell import start_menu
        body = self._source(start_menu, '    def on_activate',
                            '    def apply_skin_settings')
        self.assertIn('IsDescendant', body,
                      "the menu re-focuses itself when it is already focused")
        self.assertLess(body.index('IsDescendant'), body.index('SetFocus'))

    def test_the_classic_menu_hands_over_the_same_way(self):
        from src.ui import classic_start_menu
        body = self._source(classic_start_menu, '    def on_activate',
                            '    def check_and_hide')
        self.assertLess(body.index('_focus_pending'), body.index('focus_now'))
        with open(classic_start_menu.__file__, encoding='utf-8') as handle:
            self.assertIn('def _hand_over_focus', handle.read())

    def test_a_key_before_the_hand_over_is_never_lost(self):
        from src.shell import start_menu
        hook = self._source(start_menu, '    def _on_char_hook',
                            '    def position_menu')
        self.assertIn('self._hand_over_focus()', hook)


class ShellWindowKeysTests(unittest.TestCase):
    """A key pressed in a shell window is that window's key.

    `EVT_CHAR_HOOK` is not confined to the window it is bound to: it travels
    up the parent chain, and every shell window is a frame whose parent is
    Titan's main window.  So the main window's own char hook was answering
    keys pressed on the desktop, on the taskbar, in the Start menu and in the
    file browser - which is why a full stop typed into the browser's address
    band was read as the Buffer System's "next element" and never reached the
    field.
    """

    def test_a_key_in_a_child_frame_arrives_at_the_parent(self):
        """The mechanism itself - this is why the guard has to exist."""
        seen = []
        parent = wx.Frame(None)
        parent.Bind(wx.EVT_CHAR_HOOK, lambda e: (seen.append(e.GetKeyCode()),
                                                 e.Skip()))
        child = wx.Frame(parent)
        field = wx.TextCtrl(child)
        try:
            event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
            event.SetEventObject(field)
            event.SetId(field.GetId())
            # ProcessEvent on the child's handler chain is what wx does with
            # a char hook that the focused window did not claim.
            field.GetEventHandler().ProcessEvent(event)
            self.assertTrue(
                seen, "wx no longer propagates a char hook to the parent "
                      "frame; the containment guard can go")
        finally:
            child.Destroy()
            parent.Destroy()

    def test_the_main_window_ignores_another_window_s_key(self):
        from src.ui.gui import TitanApp
        parent = wx.Frame(None)
        own = wx.TextCtrl(parent)
        shell_window = wx.Frame(parent)          # the desktop, the browser...
        theirs = wx.TextCtrl(shell_window)
        try:
            event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
            event.SetEventObject(theirs)
            self.assertFalse(
                TitanApp._key_belongs_to_this_window(parent, event, None),
                "the main window still answers keys pressed in a shell window")

            mine = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
            mine.SetEventObject(own)
            self.assertTrue(
                TitanApp._key_belongs_to_this_window(parent, mine, None),
                "the main window stopped answering its own keys")
        finally:
            shell_window.Destroy()
            parent.Destroy()

    def test_the_guard_runs_before_the_buffer_keys(self):
        """Order matters: the buffer branch is the first thing in there."""
        from src.ui import gui as gui_module
        source = open(gui_module.__file__, encoding='utf-8').read()
        body = source[source.index('    def on_key_down(self, event):'):]
        body = body[:body.index('    def handle_navigation')]
        self.assertLess(body.index('_key_belongs_to_this_window'),
                        body.index('buffer_controller'),
                        "the Buffer System still sees other windows' keys")

    def test_the_browser_hands_unclaimed_keys_to_its_controls(self):
        """A full stop is the list's first-letter jump or a typed character."""
        from src.shell import explorer
        source = open(explorer.__file__, encoding='utf-8').read()
        hook = source[source.index('    def _on_char_hook'):
                      source.index('    def panes(self)')]
        self.assertTrue(hook.rstrip().endswith('event.Skip()'),
                        "the browser swallows the keys it does not answer")


# --------------------------------------------------------------------------- #
# 21. The classic Start menu
# --------------------------------------------------------------------------- #
class ClassicStartMenuTests(unittest.TestCase):
    """Windows 95's menu, with everything the XP one lists on it.

    The two menus are faces of one menu: the entries come from
    `src/ui/start_menu_content.py`, so the classic one cannot quietly fall
    behind the other again - which is what had happened, it having neither
    the macros nor the Titan IM modules nor the packaged Windows apps.
    """

    def setUp(self):
        from src.ui.classic_start_menu import ClassicStartMenu
        self.menu = ClassicStartMenu(None)
        self.addCleanup(self._destroy)

    def _destroy(self):
        self.menu.allow_close()
        self.menu.Destroy()

    def _labels(self, entries):
        return [entry.label for entry in entries]

    # -- what is on it ------------------------------------------------------
    def test_the_top_level_is_reactos_own_start_menu(self):
        """`IDM_STARTMENU`: Programs, Documents, Settings, Search, then out."""
        kinds = [(entry.kind, entry.payload)
                 for entry in self.menu._top_level_entries()]
        # A shell add-on contributing a branch is the system working, not the
        # menu drifting - this is about the entries that are Titan's own, so
        # an add-on's are left out rather than making the suite depend on
        # which add-ons the machine it runs on has switched on.
        self.assertEqual(
            [payload for kind, payload in kinds
             if kind == 'folder' and not _is_addon_payload(payload)],
            ['__programs__', '__documents__', '__settings__', '__find__'])
        actions = [payload for kind, payload in kinds if kind == 'action']
        self.assertEqual(actions[-4:], ['help', 'run', 'logoff', 'shutdown'])
        self.assertEqual([kind for kind, payload in kinds].count('separator'),
                         1, "the separator before Log Off is missing")

    def test_the_separator_is_a_word_and_not_a_row_of_dashes(self):
        """A menu item's text is its accessible name."""
        labels = self._labels(self.menu._top_level_entries())
        self.assertNotIn('---', labels)
        for label in labels:
            self.assertNotIn('---', label)

    def test_log_off_names_the_user_as_windows_does(self):
        entry = [item for item in self.menu._top_level_entries()
                 if item.payload == 'logoff'][0]
        user = os.environ.get('USERNAME') or os.environ.get('USER')
        if user:
            self.assertIn(user, entry.label)

    def test_the_macros_and_the_im_modules_are_in_programs(self):
        """The two things the classic menu was missing."""
        payloads = [entry.payload for entry in self.menu._programs_entries()]
        for branch in ('__apps__', '__games__', '__im__', '__macros__',
                       '__windows_apps__'):
            self.assertIn(branch, payloads)

    def test_titan_im_lists_the_services_titan_brings_itself(self):
        labels = self._labels(self.menu._im_entries())
        for service in ('Telegram', 'WhatsApp', 'Titan-Net'):
            self.assertIn(service, labels)

    def test_every_branch_of_the_menu_can_be_opened(self):
        """A branch that answers nothing is a branch that opens on nothing."""
        seen = set()
        stack = list(self.menu._top_level_entries())
        while stack:
            entry = stack.pop()
            if entry.kind != 'folder':
                continue
            if isinstance(entry.payload, str):
                if entry.payload in seen:
                    continue
                seen.add(entry.payload)
            children = self.menu._children_of(entry)
            self.assertIsInstance(children, list, entry.label)
            self.assertTrue(children, f"{entry.label} opens on nothing")
            stack.extend(child for child in children if child.kind == 'folder')
        for branch in ('__programs__', '__documents__', '__settings__',
                       '__find__', '__apps__', '__games__', '__im__',
                       '__macros__', '__windows_apps__'):
            self.assertIn(branch, seen, f"{branch} was never reached")

    def test_the_settings_branch_has_what_reactos_settings_has(self):
        payloads = [entry.payload for entry in self.menu._settings_entries()]
        for expected in ('titan_settings', 'control_panel',
                         'taskbar_properties', 'printers',
                         'network_connections'):
            self.assertIn(expected, payloads)

    def test_the_recent_documents_are_opened_like_any_shortcut(self):
        for entry in self.menu._recent_documents():
            self.assertEqual(entry.kind, 'program')
            self.assertEqual(entry.payload['type'], 'shortcut')

    def test_the_search_index_reaches_inside_the_branches(self):
        """Somebody typing three letters is looking for a thing."""
        index = self.menu._build_search_index()
        self.assertTrue(index)
        self.assertFalse([entry for entry in index
                          if entry.kind in ('folder', 'separator', 'back')],
                         "a branch cannot be a search result")

    def test_the_search_finds_a_setting_by_its_name(self):
        # Searched for by the word the menu itself shows, because that word
        # is translated: a Polish Titan calls it "Panel sterowania" and
        # "control" would find nothing at all.
        wanted = [entry for entry in self.menu._settings_entries()
                  if entry.payload == 'control_panel'][0]
        results = self.menu.search_entries(wanted.label.split()[0][:5])
        self.assertTrue([entry for entry in results
                         if entry.payload == 'control_panel'])

    # -- how it behaves -----------------------------------------------------
    def test_a_separator_does_nothing_when_it_is_activated(self):
        separator = [entry for entry in self.menu._top_level_entries()
                     if entry.kind == 'separator'][0]
        done = []
        self.menu._run_action = lambda action: done.append(action)
        self.menu._activate_entry(separator)
        self.assertEqual(done, [])

    def test_a_branch_is_the_same_control_the_xp_menu_uses(self):
        from src.ui.start_menu_content import MenuTree
        self.assertIsInstance(self.menu.menu_tree, MenuTree)

    def test_escape_closes_the_branch_before_it_closes_the_menu(self):
        tree = self.menu.menu_tree
        first = tree.GetFirstChild(tree.GetRootItem())[0]
        branch = tree.GetNextSibling(first)      # Programs
        tree.SelectItem(branch)
        tree.Expand(branch)
        self.assertTrue(self.menu._collapse_current_branch())
        self.assertFalse(tree.IsExpanded(branch))
        self.assertFalse(self.menu._collapse_current_branch(),
                         "a menu with nothing open would not close")

    def test_the_menu_is_hidden_and_never_destroyed(self):
        """Titan keeps one of these; destroying it crashed the next open."""
        event = wx.CloseEvent(wx.wxEVT_CLOSE_WINDOW)
        event.SetCanVeto(True)
        self.menu.on_close(event)
        self.assertTrue(event.GetVeto())
        self.assertFalse(self.menu.IsShown())

    def test_the_banner_is_decoration_and_takes_no_focus(self):
        self.assertFalse(self.menu.banner.AcceptsFocus())
        self.assertFalse(self.menu.banner.AcceptsFocusFromKeyboard())

    # -- the repairs --------------------------------------------------------
    def test_a_game_is_run_through_the_module_games_actually_live_in(self):
        """`import game_manager` is not where it lives - every game raised."""
        with open('src/ui/classic_start_menu.py', encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('from game_manager import', source)
        self.assertIn('from src.titan_core.game_manager import', source)

    def test_the_settings_open_through_the_one_place_that_knows_which(self):
        """It used to import `SettingsFrame` - from the wrong module, and
        then from the right one.  It now builds no settings window at all:
        which window the settings open in is the user's choice (Settings ->
        Interface -> Settings interface), and `src/settings/interfaces.py`
        is the only thing that knows it.  A menu with an opinion of its own
        would open the classic window for somebody who had chosen another.
        """
        with open('src/ui/classic_start_menu.py', encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('from settingsgui import', source)
        # A call, not the word: the docstring above `show_titan_settings`
        # says what it no longer does, and saying so is the point of it.
        self.assertNotIn('SettingsFrame(', source)
        self.assertIn('from src.settings.interfaces import open_settings',
                      source)

    def test_a_loose_shortcut_in_programs_is_not_thrown_away(self):
        """Windows 95 shows them at the top of Programs, not nowhere."""
        structure = self.menu.load_windows_programs_with_folders()
        self.assertIsInstance(structure, dict)
        for item in structure.get('', []):
            self.assertIn('path', item)

    def test_both_menus_read_from_one_set_of_contents(self):
        """The classic menu fell behind because it had contents of its own."""
        from src.shell.start_menu import XPStartMenu
        from src.ui.classic_start_menu import ClassicStartMenu
        from src.ui.start_menu_content import StartMenuContent
        self.assertTrue(issubclass(ClassicStartMenu, StartMenuContent))
        self.assertTrue(issubclass(XPStartMenu, StartMenuContent))
        for shared in ('_im_entries', '_macro_entries', '_windows_app_entries',
                       '_settings_entries', '_titan_app_entries',
                       '_build_search_index'):
            self.assertNotIn(shared, XPStartMenu.__dict__,
                             f"{shared} is written twice")
            self.assertNotIn(shared, ClassicStartMenu.__dict__,
                             f"{shared} is written twice")

    def test_one_char_hook_answers_a_key_in_either_menu(self):
        """Two bindings would run both menus' Escape for one press."""
        with open('src/shell/start_menu.py', encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('EVT_CHAR_HOOK, self._on_char_hook', source)
        self.assertIn('def on_char_hook', source)


class ClassicStartMenuInTheShellTests(unittest.TestCase):
    """With the shell up it is the shell's menu, not a Titan window."""

    def test_escape_lands_on_the_start_button(self):
        from src.ui.classic_start_menu import ClassicStartMenu
        pressed = []
        shell = types.SimpleNamespace(
            focus_start_button=lambda: pressed.append(True) or True,
            set_start_button_pressed=lambda value: None,
            taskbar_height=lambda: 30)
        menu = ClassicStartMenu(None, shell=shell)
        try:
            event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
            event.SetKeyCode(wx.WXK_ESCAPE)
            menu.on_char_hook(event)
            self.assertEqual(pressed, [True])
            self.assertFalse(menu.IsShown())
        finally:
            menu.allow_close()
            menu.Destroy()

    def test_the_shell_gets_the_classic_menu_it_asked_for(self):
        """The style setting picks the face; both are given the shell."""
        with open('src/shell/shell_manager.py', encoding='utf-8') as handle:
            source = handle.read()
        body = source[source.index('    def get_start_menu'):
                      source.index('    def toggle_start_menu')]
        self.assertIn('ClassicStartMenu(self.parent', body)
        self.assertIn('shell=self', body)

    def test_a_folder_opens_in_the_shells_own_browser(self):
        from src.ui.classic_start_menu import ClassicStartMenu
        opened = []
        shell = types.SimpleNamespace(
            open_explorer=lambda *args: opened.append(args or ('',)),
            set_start_button_pressed=lambda value: None,
            focus_start_button=lambda: True,
            taskbar_height=lambda: 30)
        menu = ClassicStartMenu(None, shell=shell)
        try:
            menu.show_find_dialog()
            self.assertEqual(len(opened), 1)
        finally:
            menu.allow_close()
            menu.Destroy()


class ModifierKeysTests(unittest.TestCase):
    """A modifier is held only while the user is holding it.

    Two mechanisms of Titan's own could say otherwise, and both belong to
    the shell.  The `keyboard` library's suppression of a whole HOTKEY turns
    on a state machine that swallows every modifier key down and replays it
    as a synthetic press later, keyed on scan codes that outlive the events
    that set them; and `AttachThreadInput` - how the bar takes the keyboard
    - merges this thread's input queue with another program's, which is
    where the per-thread key state `wxKeyEvent::ShiftDown()` answers from.
    """

    def test_the_shell_registers_no_suppressed_hotkey(self):
        """Measured: one suppressed hotkey costs every modifier in the session.

        With `ctrl+esc` registered through `keyboard.add_hotkey(...,
        suppress=True)`, `blocking_hotkeys` is non-empty, which is the whole
        condition `_KeyboardListener.direct_callback` runs its modifier
        transition table on - after which Control key downs are suppressed
        and injected back by hand.  A suppressing KEY hook leaves that
        machinery switched off.
        """
        with open('src/titan_core/tce_system.py', encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('suppress=True, trigger_on_release=False', source)
        self.assertIn('def _make_combination_hook', source)

    def test_a_combination_claims_the_pair_and_not_the_key(self):
        """Escape stays Escape; only Ctrl+Escape belongs to Titan."""
        from src.titan_core import tce_system
        import keyboard as kb

        manager = tce_system.SystemHooksManager()
        hooked = []
        manager._add_hook = lambda key, callback: hooked.append((key, callback))
        manager._handle_start_menu_ctrl_esc = lambda: None
        manager._add_combination('start_menu_ctrl_esc', 'ctrl+esc')

        self.assertEqual([key for key, _cb in hooked], ['esc'])
        hook = hooked[0][1]
        event = types.SimpleNamespace(event_type=kb.KEY_DOWN)
        release = types.SimpleNamespace(event_type=kb.KEY_UP)

        original = tce_system._key_physically_down
        try:
            tce_system._key_physically_down = lambda vk: False
            self.assertTrue(hook(event), "bare Escape must reach the program")
            tce_system._key_physically_down = lambda vk: True
            self.assertFalse(hook(event), "Ctrl+Escape belongs to Titan")
            self.assertTrue(hook(release), "the release is never swallowed")
        finally:
            tce_system._key_physically_down = original

    def test_a_shift_only_the_queue_remembers_is_not_a_shift(self):
        from src.system import key_state

        class Event:
            def __init__(self, mask):
                self._mask = mask

            def GetModifiers(self):
                return self._mask

            def ShiftDown(self):
                return bool(self._mask & wx.MOD_SHIFT)

        original = key_state.physically_down
        try:
            key_state.physically_down = lambda vk: False
            self.assertEqual(key_state.modifiers(Event(wx.MOD_SHIFT)), wx.MOD_NONE)
            self.assertFalse(key_state.shift_down(Event(wx.MOD_SHIFT)))
            # Control and Alt are left exactly as reported - nothing latches
            # them, and guessing about them would break real shortcuts.
            self.assertEqual(key_state.modifiers(Event(wx.MOD_CONTROL)),
                             wx.MOD_CONTROL)
            key_state.physically_down = lambda vk: True
            self.assertTrue(key_state.shift_down(Event(wx.MOD_SHIFT)))
            self.assertFalse(key_state.shift_down(Event(wx.MOD_NONE)))
        finally:
            key_state.physically_down = original

    def test_the_shell_asks_windows_about_shift_everywhere(self):
        """No shell key handler reads Shift straight off the event."""
        for name in ('controls', 'desktop', 'explorer', 'start_menu', 'taskbar'):
            with open('src/shell/%s.py' % name, encoding='utf-8') as handle:
                source = handle.read()
            self.assertNotIn('event.ShiftDown()', source, name)


class DeferredCallTests(unittest.TestCase):
    """Work queued for later must never fire into a window that has gone.

    This is the crash the shell produced most often: a taskbar button asks
    Windows to activate a window and rebuilds the bar 120 ms later, the shell
    is switched off in the meantime, and the timer calls a method of a frame
    whose C++ side no longer exists - a RuntimeError raised inside wx's event
    loop, where nothing catches it.
    """

    def setUp(self):
        from src.shell import deferred
        self.deferred = deferred
        self.frame = wx.Frame(None)

    def tearDown(self):
        try:
            self.frame.Destroy()
        except Exception:
            pass

    def test_a_living_window_is_alive_and_a_destroyed_one_is_not(self):
        self.assertTrue(self.deferred.alive(self.frame))
        self.frame.Destroy()
        wx.Yield()
        self.assertFalse(self.deferred.alive(self.frame))
        self.assertFalse(self.deferred.alive(None))

    def test_a_call_queued_for_a_window_that_goes_is_dropped(self):
        ran = []
        timer = self.deferred.call_later(self.frame, 10000,
                                         lambda: ran.append(1))
        self.frame.Destroy()
        wx.Yield()
        self.assertFalse(self.deferred.alive(self.frame))
        # What the timer does when it fires, without waiting ten seconds
        # for it: the window has gone, so the work does not happen.
        timer.Notify()
        timer.Stop()
        self.assertEqual(ran, [])

    def test_a_call_for_a_window_that_is_still_there_runs(self):
        ran = []
        self.deferred.call_after(self.frame, lambda: ran.append(1))
        wx.Yield()
        self.assertEqual(ran, [1])

    def test_a_call_that_touches_a_dead_object_does_not_raise(self):
        """A queued call must never raise into wx's event loop."""
        other = wx.Frame(None)
        other.Destroy()
        wx.Yield()
        self.deferred.call_after(self.frame, other.GetTitle)
        wx.Yield()          # no exception is the assertion

    def test_a_burst_of_asks_is_one_piece_of_work(self):
        ran = []
        once = self.deferred.Coalesced(self.frame, lambda: ran.append(1))
        for _ in range(500):
            once.request()
        wx.Yield()
        self.assertEqual(ran, [1])
        once.request()
        wx.Yield()
        self.assertEqual(ran, [1, 1])

    def test_a_cancelled_burst_never_happens(self):
        ran = []
        once = self.deferred.Coalesced(self.frame, lambda: ran.append(1))
        once.request()
        once.cancel()
        wx.Yield()
        self.assertEqual(ran, [])

    def test_the_shell_never_queues_a_bare_wx_call_on_its_own_window(self):
        """Every deferral in the shell goes through the guarded helpers."""
        import re
        allowed = {
            # `_appbar_ready` has to run even when the bar has gone: it is
            # what unregisters the appbar, so the strip is given back.
            'taskbar.py': ['wx.CallAfter(self._appbar_ready, appbar, rect)'],
            # The desktop's own reader checks "if not self" itself.
            'desktop.py': ['wx.CallAfter(self._apply_read, entries, handles)'],
        }
        pattern = re.compile(r'wx\.Call(?:After|Later)\([^\n]*')
        for name in ('taskbar.py', 'desktop.py', 'explorer.py',
                     'start_menu.py', 'quick_launch.py',
                     'taskbar_properties.py'):
            with open('src/shell/' + name, encoding='utf-8') as handle:
                source = handle.read()
            for call in pattern.findall(source):
                self.assertIn(call.strip(), allowed.get(name, []),
                              '%s: %s' % (name, call))


class ExplorerSpeedTests(unittest.TestCase):
    """What made a folder of three thousand files unusable, and what fixed it.

    Measured before the change, on such a folder: opening it 5951 ms, sorting
    a column 1054 ms, Ctrl+A 37717 ms and F5 51624 ms.  Every one of those was
    the same mistake in a different place - asking Windows about every file,
    or asking the list control about every row, when neither had to be asked
    at all.
    """

    @classmethod
    def setUpClass(cls):
        import shutil
        import tempfile
        from src.shell import explorer
        cls.shutil = shutil
        cls.explorer = explorer
        cls.folder = tempfile.mkdtemp(prefix='titan_explorer_')
        for index in range(60):
            for extension in ('.txt', '.log', '.dat'):
                open(os.path.join(cls.folder, 'file_%03d%s'
                                  % (index, extension)), 'w').close()
        os.mkdir(os.path.join(cls.folder, 'a folder'))
        cls.frame = explorer.ExplorerFrame(None, explorer.COMPUTER)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.frame.Destroy()
        except Exception:
            pass
        cls.shutil.rmtree(cls.folder, ignore_errors=True)

    def setUp(self):
        self.frame.set_view(self.explorer.VIEW_DETAILS)
        self.frame.navigate(self.folder)

    def test_the_details_view_is_a_virtual_list(self):
        """The rows are asked for, not inserted - which is the whole win."""
        self.assertTrue(self.frame.list.IsVirtual())
        self.assertEqual(self.frame.list.GetItemCount(),
                         len(self.frame.entries))

    def test_a_virtual_row_answers_with_its_own_cells(self):
        row = [entry['name'] for entry in self.frame.entries].index('a folder')
        self.assertEqual(self.frame.cell_at(row, 0), 'a folder')
        self.assertTrue(self.frame.cell_at(row, 2))
        self.assertGreaterEqual(self.frame.image_at(row), 0)

    def test_a_row_that_is_not_there_answers_rather_than_raising(self):
        """A virtual list asks about rows the folder no longer has."""
        self.assertEqual(self.frame.cell_at(10 ** 6, 0), '')
        self.assertEqual(self.frame.cell_at(-1, 0), '')
        self.assertEqual(self.frame.image_at(10 ** 6), -1)

    def test_windows_is_asked_a_type_once_per_extension(self):
        """Not once per file: it was three thousand shell calls a folder."""
        from src.shell import explorer, win_shell
        explorer.clear_caches()
        asked = []
        real = win_shell.file_type_name

        def counted(path):
            asked.append(path)
            return real(path)

        explorer.win_shell.file_type_name = counted
        try:
            for entry in explorer.list_folder(self.folder):
                explorer.type_name_of(entry)
        finally:
            explorer.win_shell.file_type_name = real
        self.assertEqual(len(asked), 3, asked)

    def test_the_icon_cache_outlives_a_navigation(self):
        """Going into a folder and back must not re-fetch every icon."""
        cache = self.frame._icon_cache(self.explorer.SMALL_ICON)
        self.frame.navigate(self.explorer.COMPUTER)
        self.frame.navigate(self.folder)
        self.assertIs(self.frame._icon_cache(self.explorer.SMALL_ICON), cache)

    def test_the_image_lists_are_lent_to_the_list_never_given(self):
        """AssignImageList would destroy the cache on the next view."""
        source = open(self.explorer.__file__, encoding='utf-8').read()
        self.assertNotIn('.AssignImageList(', source)
        self.assertIn('.SetImageList(', source)

    def test_selecting_everything_is_one_piece_of_work(self):
        """A status bar worked out per selected file is what took 37 s."""
        updates = []
        real = self.frame._update_status
        self.frame._update_status = lambda: (updates.append(1), real())[1]
        try:
            self.frame.select_all()
            wx.Yield()
        finally:
            self.frame._update_status = real
        self.assertEqual(self.frame.selected_count(),
                         len(self.frame.entries))
        self.assertLessEqual(len(updates), 2, len(updates))

    def test_the_status_bar_says_how_many_are_selected(self):
        self.frame.select_all()
        wx.Yield()
        first = self.frame.status_texts()[0]
        self.assertIn(str(len(self.frame.entries)), first)

    def test_a_refresh_puts_the_whole_selection_back(self):
        self.frame.select_all()
        self.frame.refresh()
        self.assertEqual(self.frame.selected_count(),
                         len(self.frame.entries))

    def test_a_refresh_puts_one_selected_file_back(self):
        wanted = self.frame.entries[1]['path']
        self.frame._select_paths([wanted])
        self.frame.refresh()
        self.assertEqual([entry['path']
                          for entry in self.frame.selected_entries()],
                         [wanted])

    def test_an_icon_view_fills_itself_in_blocks(self):
        """wxWidgets will not make an icon view virtual, so it is chunked."""
        self.frame.set_view(self.explorer.VIEW_LARGE)
        try:
            self.frame.navigate(self.folder, remember=False)
            self.assertFalse(self.frame.list.IsVirtual())
            # This folder arrives in one block; either way the list is whole
            # the moment anything asks for every row.
            self.frame._finish_fill()
            self.assertEqual(self.frame.list.GetItemCount(),
                             len(self.frame.entries))
        finally:
            self.frame.set_view(self.explorer.VIEW_DETAILS)

    def test_the_folders_bar_reads_only_the_folders(self):
        """It wanted the directories, not every file in the folder."""
        entries = self.explorer.subfolders(self.folder)
        self.assertEqual([entry['name'] for entry in entries], ['a folder'])

    def test_one_navigation_at_a_time(self):
        """The folders bar navigating under a navigation must not nest."""
        self.frame._navigating = True
        try:
            self.assertFalse(self.frame.navigate(self.explorer.COMPUTER))
        finally:
            self.frame._navigating = False

    def test_a_folder_that_answers_late_still_fills_the_window(self):
        """The window waits only so long, then fills in when the answer comes."""
        import time as clock
        from src.shell import explorer
        real = explorer.list_location
        real_wait = explorer.READ_WAIT
        explorer.READ_WAIT = 0.05

        def slow(location, show_hidden=False):
            clock.sleep(0.35)
            return real(location, show_hidden)

        self.frame.navigate(self.explorer.COMPUTER)
        explorer.list_location = slow
        try:
            self.assertTrue(self.frame.navigate(self.folder))
            # Not read yet: the window went back to answering the keyboard.
            self.assertTrue(self.explorer.is_computer(self.frame.location))
            deadline = clock.time() + 5
            while clock.time() < deadline and \
                    self.explorer.is_computer(self.frame.location):
                wx.Yield()
                clock.sleep(0.02)
        finally:
            explorer.list_location = real
            explorer.READ_WAIT = real_wait
        self.assertEqual(os.path.normcase(str(self.frame.location)),
                         os.path.normcase(self.folder))
        self.assertEqual(self.frame.list.GetItemCount(),
                         len(self.frame.entries))

    def test_a_stale_answer_is_never_shown_over_a_newer_one(self):
        request = {'token': self.frame._read_token - 1,
                   'location': self.folder, 'entries': []}
        self.assertFalse(self.frame._apply_read(request))

    def test_a_window_that_is_closing_drops_what_it_asked_for(self):
        frame = self.explorer.ExplorerFrame(None, self.explorer.COMPUTER)
        token = frame._read_token
        frame._on_close(FakeCloseEvent())
        self.assertGreater(frame._read_token, token)
        frame.Destroy()


class FakeCloseEvent:
    def Skip(self):
        return None


class DriveReadingTests(unittest.TestCase):
    """A drive with nothing in it is a blank size, never a modal dialog."""

    def test_the_drives_are_read_with_the_media_error_box_switched_off(self):
        source = open(win_shell.__file__, encoding='utf-8').read()
        body = source[source.index('def list_drives'):
                      source.index('def _list_drives')]
        self.assertIn('quiet_media_errors', body)

    def test_the_error_mode_is_this_threads_and_is_put_back(self):
        with win_shell.quiet_media_errors():
            pass
        # Asked for per thread, never for the whole of Titan: the
        # process-wide call would change how every other part of Titan
        # behaves on another thread at that moment.
        source = open(win_shell.__file__, encoding='utf-8').read()
        self.assertIn('SetThreadErrorMode', source)
        self.assertNotIn('kernel32.SetErrorMode(', source)

    def test_the_drives_still_come_back(self):
        drives = win_shell.list_drives()
        self.assertTrue(drives)
        self.assertTrue(all(drive.get('root') for drive in drives))


class ShellHookLifetimeTests(unittest.TestCase):
    """Windows holds the ADDRESS of a callback Python could collect."""

    def test_an_installed_hook_is_kept_alive_until_it_is_removed(self):
        frame = wx.Frame(None)
        hook = win_shell.ShellHook(frame.GetHandle())
        try:
            if not hook.install():
                self.skipTest("the shell hook could not be installed here")
            self.assertIn(hook, win_shell._INSTALLED_HOOKS)
            hook.uninstall()
            self.assertNotIn(hook, win_shell._INSTALLED_HOOKS)
        finally:
            frame.Destroy()


class SettingsReadingTests(unittest.TestCase):
    """The settings file is parsed when it changes, not when it is asked.

    This is here rather than with the settings because it is the SHELL that
    made it matter: a taskbar asks whether it has a clock and a Show Desktop
    button on every paint, whether it is locked on every layout, and whether
    it auto-hides ten times a second - and every one of those used to open,
    read and parse the whole of `bg5settings.ini`.  Measured: a thousand
    reads of one setting, 169 ms before and 1 ms after.
    """

    def setUp(self):
        from src.settings import settings
        self.settings = settings
        settings.invalidate_settings_cache()
        self.addCleanup(settings.invalidate_settings_cache)
        self.addCleanup(self._remove_probe)

    def _remove_probe(self):
        stored = self.settings.load_settings()
        if stored.pop('titan_shell_probe', None) is not None:
            self.settings.save_settings(stored)

    def test_the_file_is_read_once_however_often_it_is_asked(self):
        reads = []
        real = self.settings._parse_settings

        def counted():
            reads.append(1)
            return real()

        self.settings._parse_settings = counted
        try:
            for _ in range(200):
                self.settings.get_setting('language', 'pl', 'general')
        finally:
            self.settings._parse_settings = real
        self.assertEqual(len(reads), 1, len(reads))

    def test_a_setting_just_written_reads_back_at_once(self):
        """A file system whose timestamps lag must not hide a new value."""
        self.settings.set_setting('probe', 'one', 'titan_shell_probe')
        self.assertEqual(
            self.settings.get_setting('probe', None, 'titan_shell_probe'),
            'one')
        self.settings.set_setting('probe', 'two', 'titan_shell_probe')
        self.assertEqual(
            self.settings.get_setting('probe', None, 'titan_shell_probe'),
            'two')

    def test_what_load_settings_hands_back_is_the_callers_own(self):
        """The settings wizard keeps its dictionary and changes it."""
        first = self.settings.load_settings()
        self.assertIsNot(first, self.settings.load_settings())
        first['titan_shell_probe'] = {'probe': 'not saved'}
        self.assertIsNone(
            self.settings.get_setting('probe', None, 'titan_shell_probe'))

    def test_a_change_made_outside_this_process_is_noticed(self):
        self.settings.set_setting('probe', 'one', 'titan_shell_probe')
        stored = self.settings.load_settings()
        stored['titan_shell_probe']['probe'] = 'changed by somebody else'
        # Written the way another program would write it - behind the cache.
        with open(self.settings.SETTINGS_FILE_PATH, 'w',
                  encoding='utf-8') as handle:
            for section, values in stored.items():
                handle.write('[%s]\n' % section)
                for key, value in values.items():
                    handle.write('%s=%s\n' % (key, value))
                handle.write('\n')
        time.sleep(self.settings.STAT_INTERVAL + 0.05)
        self.assertEqual(
            self.settings.get_setting('probe', None, 'titan_shell_probe'),
            'changed by somebody else')

    def test_no_settings_file_is_no_settings_rather_than_an_error(self):
        real_path = self.settings.SETTINGS_FILE_PATH
        self.settings.SETTINGS_FILE_PATH = real_path + '.nonexistent'
        self.settings.invalidate_settings_cache()
        try:
            self.assertEqual(self.settings.load_settings(), {})
            self.assertEqual(self.settings.get_setting('anything', 'default'),
                             'default')
        finally:
            self.settings.SETTINGS_FILE_PATH = real_path
            self.settings.invalidate_settings_cache()


class ClockRepaintTests(unittest.TestCase):
    """The clock is told the time every second; it changes once a minute."""

    def test_the_same_time_and_the_same_name_repaint_nothing(self):
        from src.shell.controls import TextControl
        frame = wx.Frame(None)
        try:
            control = TextControl(frame, name='clock')
            painted = []
            control.Refresh = lambda *args, **kwargs: painted.append(1)
            control.set_text('12:30', name='12:30, Friday')
            self.assertEqual(len(painted), 1)
            control.set_text('12:30', name='12:30, Friday')
            self.assertEqual(len(painted), 1, "it repainted for nothing")
            control.set_text('12:31', name='12:31, Friday')
            self.assertEqual(len(painted), 2)
        finally:
            frame.Destroy()


class PackagedAppTests(unittest.TestCase):
    """"Windows apps" means the Store apps, and only those.

    `shell:AppsFolder` holds both: the packaged applications, which exist
    nowhere else on the machine, and every desktop program's shortcut, Steam
    URL and auto-generated entry besides.  Measured here: 309 entries, 60 of
    them packaged - so a branch listing all of them was a second, worse copy
    of All Programs with the Store apps buried in it.
    """

    def test_a_packaged_app_is_told_by_the_shape_of_its_id(self):
        for app_id in ('Microsoft.WindowsCamera_8wekyb3d8bbwe!App',
                       'Microsoft.Copilot_8wekyb3d8bbwe!App',
                       'AdobeSystemsIncorporated.AdobePhotoshopExpress'
                       '_mtcwf2zmmt10c!App'):
            self.assertTrue(win_shell.is_packaged_app(app_id), app_id)

    def test_everything_else_in_the_apps_folder_is_not_one(self):
        for app_id in (
                'steam://rungameid/1228500',
                r'{6D809377-6AF0-444B-8957-A3773F02200E}\7-Zip\7zFM.exe',
                r'C:\Users\me\AppData\Local\Programs\Thing\thing.exe',
                'Microsoft.AutoGenerated.{1BEB6467-F4A7-16AE-72BE-F427253BD6}',
                'AcrobatReader', 'Microsoft.Office.MSACCESS.EXE.15', '', None):
            self.assertFalse(win_shell.is_packaged_app(app_id), app_id)

    def test_a_path_with_an_exclamation_mark_is_not_a_packaged_app(self):
        """The `!` alone is not enough - a file name may contain one."""
        self.assertFalse(win_shell.is_packaged_app(r'C:\Games\Portal 2!\p2.exe'))

    def test_the_filter_is_what_the_branch_asks_for(self):
        everything = win_shell.installed_apps()
        packaged = win_shell.installed_apps(packaged_only=True)
        self.assertLessEqual(len(packaged), len(everything))
        self.assertTrue(all(win_shell.is_packaged_app(app_id)
                            for _name, app_id in packaged))


class StartMenuSpeedTests(unittest.TestCase):
    """Both menus open at once, and neither waits for Windows to answer.

    Measured before this: opening the classic menu 60.7 ms and the XP one
    58.2 ms, of which 14 was putting ten unchanged items back into a tree
    control - and the Windows apps branch took 897 ms the first time it was
    opened, because it read the whole Apps folder on the GUI thread.
    """

    @classmethod
    def setUpClass(cls):
        from src.ui.classic_start_menu import ClassicStartMenu
        cls.menu = ClassicStartMenu(None)
        cls.menu.build_menu_structure()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.menu.Destroy()
        except Exception:
            pass

    def setUp(self):
        self.menu.build_menu_structure()

    # -- the top level is not rebuilt for nothing --------------------------
    def test_an_unchanged_top_level_is_recognised(self):
        self.assertTrue(self.menu.menu_tree.matches(
            self.menu._top_level_entries()))

    def test_a_changed_top_level_is_not(self):
        from src.ui.start_menu_content import MenuEntry
        entries = self.menu._top_level_entries()
        entries.append(MenuEntry('Something new', 'action', 'nothing'))
        self.assertFalse(self.menu.menu_tree.matches(entries))

    def test_opening_the_menu_again_keeps_the_top_level(self):
        tree = self.menu.menu_tree
        before = tree.entries
        self.menu.build_menu_structure()
        self.assertIs(tree.entries, before)

    def test_but_a_branch_reads_itself_again_on_the_next_open(self):
        """That is the whole point of rebuilding: new add-ons appear."""
        tree = self.menu.menu_tree
        branch = tree.find_branch('__programs__')
        self.assertIsNotNone(branch)
        tree.Expand(branch)
        self.assertGreater(tree.GetChildrenCount(branch, False), 1)
        self.assertTrue(tree.GetItemData(branch).filled)
        self.menu.build_menu_structure()
        branch = tree.find_branch('__programs__')
        # Back to the one placeholder child that makes it look like a branch.
        self.assertEqual(tree.GetChildrenCount(branch, False), 1)
        self.assertFalse(tree.GetItemData(branch).filled)

    def test_rebuilding_makes_no_focus_cue(self):
        """Selecting the first item again is not the user arriving anywhere."""
        from src.ui import classic_start_menu
        played = []
        real = classic_start_menu.play_sound
        classic_start_menu.play_sound = lambda name, *a, **k: played.append(name)
        try:
            self.menu.build_menu_structure()
            self.menu.menu_tree.set_entries(self.menu._top_level_entries())
        finally:
            classic_start_menu.play_sound = real
        self.assertEqual(played, [], played)

    # -- the Windows apps branch -------------------------------------------
    def test_the_windows_apps_branch_is_packaged_apps_only(self):
        win_shell.installed_apps()          # make sure the list is there
        labels = [entry.label
                  for entry in self.menu._windows_app_entries()]
        packaged = dict((name, app_id) for name, app_id
                        in win_shell.installed_apps(packaged_only=True))
        if not packaged:
            self.skipTest("this machine has no packaged apps")
        self.assertEqual(sorted(labels), sorted(packaged))

    def test_a_desktop_program_is_not_in_it(self):
        """It is in All Programs, which is where the user already looks."""
        labels = set(entry.label
                     for entry in self.menu._windows_app_entries())
        desktop = [name for name, app_id in win_shell.installed_apps()
                   if not win_shell.is_packaged_app(app_id)]
        if not desktop:
            self.skipTest("nothing but packaged apps on this machine")
        self.assertFalse(labels.intersection(desktop))

    def test_the_branch_never_waits_for_windows_to_answer(self):
        """897 ms of a branch that appears to have hung."""
        real_cache, real_at = win_shell._APPS_CACHE, win_shell._APPS_CACHE_AT
        asked = []
        real_read = win_shell._read_installed_apps
        win_shell._read_installed_apps = lambda: asked.append(1) or []
        win_shell._APPS_CACHE, win_shell._APPS_CACHE_AT = [], 0.0
        try:
            entries = self.menu._windows_app_entries()
        finally:
            win_shell._read_installed_apps = real_read
            win_shell._APPS_CACHE, win_shell._APPS_CACHE_AT = (real_cache,
                                                               real_at)
        # It said so rather than blocking, and asked in the background.
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].kind, 'separator')

    def test_the_branch_fills_itself_in_when_the_answer_comes(self):
        tree = self.menu.menu_tree
        branch = tree.find_branch('__windows_apps__', tree.find_branch(
            '__programs__')) if tree.find_branch('__programs__') else None
        # The branch lives under Programs, so Programs has to be open first.
        programs = tree.find_branch('__programs__')
        tree.Expand(programs)
        branch = tree.find_branch('__windows_apps__')
        self.assertIsNotNone(branch)
        self.assertTrue(tree.refill('__windows_apps__',
                                    self.menu._windows_app_entries()))
        self.assertTrue(tree.GetItemData(branch).filled)

    # -- the Start Menu is walked once per open ----------------------------
    def test_the_windows_start_menu_is_read_once_per_open(self):
        reads = []
        real = self.menu.load_windows_programs_with_folders
        self.menu.load_windows_programs_with_folders = lambda: (
            reads.append(1) or real())
        try:
            self.menu.build_menu_structure()
            self.menu._all_programs_entries()
            self.menu._all_programs_entries()
            self.menu._build_search_index()
        finally:
            del self.menu.load_windows_programs_with_folders
        self.assertEqual(len(reads), 1, len(reads))

    def test_and_again_on_the_next_open(self):
        """A program installed since the last open must still turn up."""
        self.menu._all_programs_entries()
        self.assertIsNotNone(self.menu._programs_structure)
        self.menu.build_menu_structure()
        self.assertIsNone(self.menu._programs_structure)


class KeyboardHandoverTests(unittest.TestCase):
    """A Titan window in front means the keys are that window's.

    The Invisible UI answers every key in the session while Titan UI mode is
    on, which is right while Titan is an application the user has put away
    and wrong the moment one of Titan's own windows is in front of them.  The
    main window has always said so; the shell's windows did not, and under the
    shell that is the common case: Windows+M minimises Titan, which starts the
    Invisible UI listening, and the same shortcut then puts the keyboard on
    the desktop - where every arrow key went to the Invisible UI instead of to
    the list of icons.
    """

    class FakeInvisibleUI:
        def __init__(self):
            self.titan_ui_mode = True
            self.titan_ui_temporarily_disabled = False
            self.disabled_by_dialog = None

        def temporarily_disable_titan_ui(self, name):
            if self.titan_ui_mode and not self.titan_ui_temporarily_disabled:
                self.titan_ui_temporarily_disabled = True
                self.disabled_by_dialog = name

        def _on_dialog_close(self, name, _event):
            if self.titan_ui_temporarily_disabled and \
                    self.disabled_by_dialog == name:
                self.titan_ui_temporarily_disabled = False
                self.disabled_by_dialog = None

    class FakeActivate:
        def __init__(self, active):
            self._active = active

        def GetActive(self):
            return self._active

    def setUp(self):
        from src.shell import keyboard_handover
        self.handover = keyboard_handover
        self.interface = self.FakeInvisibleUI()
        self._real = keyboard_handover.invisible_ui
        keyboard_handover.invisible_ui = lambda: self.interface
        self.addCleanup(setattr, keyboard_handover, 'invisible_ui', self._real)

    def test_a_window_in_front_takes_the_keyboard(self):
        self.assertTrue(self.handover.take_keyboard())
        self.assertTrue(self.interface.titan_ui_temporarily_disabled)
        self.assertEqual(self.interface.disabled_by_dialog,
                         self.handover.SHELL)

    def test_and_gives_it_back_when_it_goes(self):
        self.handover.take_keyboard()
        self.handover.give_keyboard_back()
        self.assertFalse(self.interface.titan_ui_temporarily_disabled)

    def test_an_activation_is_all_a_window_has_to_say(self):
        self.handover.follows_activation(self.FakeActivate(True))
        self.assertTrue(self.interface.titan_ui_temporarily_disabled)
        self.handover.follows_activation(self.FakeActivate(False))
        self.assertFalse(self.interface.titan_ui_temporarily_disabled)

    def test_it_never_gives_back_what_somebody_else_took(self):
        """A dialog of the main window's must not be undone by the shell."""
        self.interface.temporarily_disable_titan_ui('main_window')
        self.handover.give_keyboard_back()
        self.assertTrue(self.interface.titan_ui_temporarily_disabled)
        self.assertEqual(self.interface.disabled_by_dialog, 'main_window')

    def test_with_no_invisible_ui_it_is_simply_nothing(self):
        self.handover.invisible_ui = lambda: None
        self.assertFalse(self.handover.take_keyboard())
        self.assertFalse(self.handover.give_keyboard_back())

    def test_every_shell_window_says_so_when_it_is_activated(self):
        """The desktop, the bar, both Start menus and the file browser."""
        for name in ('src/shell/desktop.py', 'src/shell/taskbar.py',
                     'src/shell/start_menu.py', 'src/shell/explorer.py',
                     'src/ui/classic_start_menu.py'):
            with open(name, encoding='utf-8') as handle:
                source = handle.read()
            self.assertIn('handover.follows_activation(event)', source, name)

    def test_minimising_behaves_the_same_with_the_shell_up(self):
        """Titan UI belongs in the shell; which window is in front decides.

        Keeping the Invisible UI switched off under the shell answered the
        "Windows+M takes the desktop's arrow keys" bug and took Titan's own
        non-visual interface away from the users most likely to want it.
        The hand-over does that job, so minimising is one behaviour again.
        """
        with open('src/ui/gui.py', encoding='utf-8') as handle:
            source = handle.read()
        body = source[source.index('    def on_minimize'):
                      source.index('    def _give_the_keyboard_back')]
        self.assertNotIn('shell_owns_the_keyboard', body)
        self.assertIn('self.minimize_to_tray()', body)
        # And the other two answers are untouched: "tray" still means the
        # tray, and "nothing" still means the window is simply iconized.
        self.assertIn("elif action == 'tray'", body)

    def test_starting_to_listen_asks_who_is_in_front(self):
        """No activation can be waited for at the moment listening begins."""
        with open('src/ui/gui.py', encoding='utf-8') as handle:
            source = handle.read()
        body = source[source.index('    def minimize_to_tray'):
                      source.index('    def restore_from_tray')]
        self.assertIn('shell_window_in_front', body)
        self.assertIn('take_keyboard', body)

    def test_the_shell_shows_titan_through_titans_own_way_back(self):
        """`Show()` by hand left the tray icon and the Invisible UI behind."""
        for name in ('src/shell/shell_manager.py',
                     'src/titan_core/tce_system.py'):
            with open(name, encoding='utf-8') as handle:
                source = handle.read()
            self.assertIn("getattr(frame, 'restore_from_tray', None)",
                          source, name)

    def test_minimising_is_answered_by_one_handler(self):
        """Two EVT_ICONIZE handlers made minimising after a restore differ."""
        with open('src/ui/gui.py', encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('_on_window_minimize', source)
        self.assertEqual(source.count('wx.EVT_ICONIZE, self.on_minimize'), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
