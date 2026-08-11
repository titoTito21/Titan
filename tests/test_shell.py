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

    def test_a_folder_says_submenu_instead_of_showing_an_arrow(self):
        from src.shell.start_menu import MenuEntry, MenuList
        frame = wx.Frame(None)
        try:
            menu = MenuList(frame, lambda entry: None,
                            wx.WHITE, wx.BLACK, 'Test')
            menu.set_entries([MenuEntry('Programs', 'folder'),
                              MenuEntry('Run', 'action')])
            folder = menu.GetItemText(0)
            plain = menu.GetItemText(1)
            # Whatever the wording, no character may be standing in for the
            # word: a list item's text is what a screen reader reads out.
            for char in folder + plain:
                self.assertLess(ord(char), 0x2000,
                                f"a glyph is being read out: {char!r}")
            self.assertIn('Programs', folder)
            self.assertNotEqual(folder, 'Programs')
            self.assertEqual(plain, 'Run')
        finally:
            frame.Destroy()


class ForegroundTests(unittest.TestCase):
    """Switching windows must never pull the keyboard onto the bar."""

    def test_a_full_screen_app_coming_and_going_never_activates_the_bar(self):
        bar = _bar_with(windows=('Notepad',))
        raised = []
        ordered = []
        bar.Raise = lambda: raised.append(True)
        bar._set_z_order = lambda topmost=True, bottom=False: ordered.append(
            (topmost, bottom))
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
        for action in (shell_actions.shell_focus_taskbar,
                       shell_actions.shell_focus_desktop,
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

    def test_the_start_menu_has_both_columns_and_steps_back_out_of_folders(self):
        from src.shell.start_menu import XPStartMenu
        menu = XPStartMenu(None, shell=None)
        try:
            self.assertTrue(menu.left_list.entries)
            self.assertTrue(menu.right_list.entries)
            top = [entry.label for entry in menu.left_list.entries]
            folders = [entry for entry in menu.left_list.entries
                       if entry.kind == 'folder']
            self.assertTrue(folders, "there is no All Programs")
            menu._enter_folder(folders[0])
            self.assertNotEqual([e.label for e in menu.left_list.entries], top)
            self.assertEqual(menu.left_list.entries[-1].kind, 'back')
            self.assertTrue(menu._go_back())
            self.assertEqual([e.label for e in menu.left_list.entries], top)
            # And at the top there is nothing left to go back to.
            self.assertFalse(menu._go_back())
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



if __name__ == '__main__':
    unittest.main(verbosity=2)
