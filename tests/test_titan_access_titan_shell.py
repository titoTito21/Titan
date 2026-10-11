# -*- coding: utf-8 -*-
"""Titan Access reads Titan's own shell off the shell itself.

`titan_shell.py` asks the live shell objects - the taskbar's groups and
buttons, the desktop's items, the Start menu's entries - what the focused
part IS, without the shell being changed for it. Here the shell is a set
of stand-ins put into ``sys.modules`` under the shell's own names, with
the class names the module recognises; nothing opens a window, speaks or
touches the real shell. Run directly.
"""
import os
import sys
import tempfile
import types
import unittest

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='ta_titan_shell_')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'data', 'components', 'titan access'))

from titan_access import titan_shell                    # noqa: E402
from titan_access import localization                   # noqa: E402
from titan_access.contracts import AccessibleObject     # noqa: E402
from titan_access.engine import TitanAccessEngine       # noqa: E402

L = localization.L


# --------------------------------------------------------------------------- #
# Stand-ins, named as the shell names its classes
# --------------------------------------------------------------------------- #
class _Win(object):
    def __init__(self, handle=0, top=None):
        self._h, self._top = handle, top

    def GetHandle(self):
        return self._h

    def GetTopLevelParent(self):
        return self._top or self


class ShellWindow(object):
    def __init__(self, hwnd, title, active=False, minimized=False,
                 flashing=False):
        self.hwnd, self.title = hwnd, title
        self.active, self.minimized, self.flashing = active, minimized, flashing


class StartButton(_Win):
    _menu_open = False

    def shell_name(self):
        return 'Start'


class TaskButton(_Win):
    def __init__(self, window, top):
        super().__init__(0, top)
        self.window = window

    def shell_name(self):
        return self.window.title


class TrayIconButton(_Win):
    def __init__(self, icon, top):
        super().__init__(0, top)
        self.icon = icon

    def shell_name(self):
        return self.icon.text


class MenuTree(_Win):
    def __init__(self, entry):
        super().__init__(0)
        self.entry = entry

    def selected_entry(self):
        return self.entry


class _Entry(object):
    def __init__(self, label, kind, payload=None, description=''):
        self.label, self.kind = label, kind
        self.payload, self.description = payload, description


class _Bar(_Win):
    def __init__(self):
        super().__init__(100)
        self.start = StartButton(0, self)
        self.windows = [ShellWindow(1, 'Notatnik', active=True),
                        ShellWindow(2, 'Poczta', minimized=True),
                        ShellWindow(3, 'Pobieranie', flashing=True)]
        self.buttons = [TaskButton(w, self) for w in self.windows]
        self._windows = list(self.windows)
        icon = types.SimpleNamespace(text='Bateria', hidden=True,
                                     chevron=False)
        self.tray = [TrayIconButton(icon, self)]

    def groups(self):
        return [('start', [self.start]), ('tasks', list(self.buttons)),
                ('tray', list(self.tray))]

    def _group_of(self, control):
        for index, (name, controls) in enumerate(self.groups()):
            if control in controls:
                return index, name, controls
        return -1, '', []


class _List(_Win):
    def __init__(self, focused):
        super().__init__(300)
        self.focused = focused

    def GetFocusedItem(self):
        return self.focused


class _Desktop(_Win):
    def __init__(self, folder):
        super().__init__(200)
        self.list = _List(1)
        self.list._top = self
        self.items = [{'name': 'Dokumenty', 'path': folder},
                      {'name': 'notatki', 'path': os.path.join(folder, 'a.txt')}]


class _Shell(object):
    _running = True

    def __init__(self, bar, desktop):
        self.taskbar, self.desktop, self.start_menu = bar, desktop, None

    def window(self, name):
        return getattr(self, name, None)


class ShellTestCase(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='ta_desk_')
        self.bar = _Bar()
        self.desktop = _Desktop(self.folder)
        self.shell = _Shell(self.bar, self.desktop)
        manager = types.ModuleType('src.shell.shell_manager')
        manager.get_shell = lambda create=False: self.shell
        taskbar = types.ModuleType('src.shell.taskbar')
        taskbar.group_label = lambda name: {'start': 'Start',
                                            'tasks': 'Otwarte okna',
                                            'tray': 'Zasobnik'}.get(name, '')
        self.saved_modules = {name: sys.modules.get(name) for name in
                              ('src.shell.shell_manager', 'src.shell.taskbar',
                               'src.shell.explorer')}
        sys.modules['src.shell.shell_manager'] = manager
        sys.modules['src.shell.taskbar'] = taskbar
        sys.modules.pop('src.shell.explorer', None)
        self.focus = None
        self.saved_focus = titan_shell.focused_window
        titan_shell.focused_window = lambda: self.focus
        self.saved_worth = titan_shell.worth_asking
        titan_shell.worth_asking = lambda: True
        titan_shell.forget()

    def tearDown(self):
        titan_shell.focused_window = self.saved_focus
        titan_shell.worth_asking = self.saved_worth
        for name, module in self.saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class _Settings(object):
    def __init__(self, values=None):
        self.values = values or {}

    def get_bool(self, section, key, default=False):
        return self.values.get((section, key), default)

    def get(self, section, key, default=''):
        return self.values.get((section, key), default)


class _Engine(object):
    def __init__(self, values=None):
        self.settings = _Settings(values)
        self.said = []

    def speak(self, text, interrupt=True, **_):
        self.said.append(text)


def _obj(name, pos=0):
    obj = AccessibleObject(provider='uia')
    obj.role, obj.name = 'listitem', name
    obj.process_id = os.getpid()
    obj.pos_in_set = pos
    return obj


class TheTaskbarSaysWhatAButtonIs(ShellTestCase):

    def test_a_window_button_is_a_window_with_its_state_and_place(self):
        self.focus = self.bar.buttons[1]
        info = titan_shell.read(_obj('Poczta'))
        self.assertEqual(info.surface, 'taskbar')
        self.assertEqual(info.group, 'Otwarte okna')
        self.assertEqual(info.kind, L('titanShell.kind.window'))
        self.assertEqual(info.states, [L('titanShell.state.minimized')])
        self.assertEqual(info.position, (2, 3))

    def test_attention_and_active_are_said(self):
        self.focus = self.bar.buttons[2]
        self.assertIn(L('titanShell.state.attention'),
                      titan_shell.read(_obj('Pobieranie')).states)
        self.focus = self.bar.buttons[0]
        self.assertEqual(titan_shell.read(_obj('Notatnik')).states,
                         [L('titanShell.state.active')])

    def test_a_hidden_tray_icon_says_so(self):
        self.focus = self.bar.tray[0]
        info = titan_shell.read(_obj('Bateria'))
        self.assertEqual(info.kind, L('titanShell.kind.trayIcon'))
        self.assertEqual(info.states, [L('titanShell.state.hidden')])

    def test_the_group_is_said_once_on_arriving_in_it(self):
        engine = _Engine()
        self.focus = self.bar.buttons[0]
        first = titan_shell.segments_for(titan_shell.read(_obj('Notatnik')),
                                         engine)
        self.assertEqual(first[0][0][0], 'Otwarte okna')
        self.focus = self.bar.buttons[1]
        second = titan_shell.segments_for(titan_shell.read(_obj('Poczta')),
                                          engine)
        self.assertEqual(second[0], [])
        titan_shell.leave_surface('taskbar')
        third = titan_shell.segments_for(titan_shell.read(_obj('Poczta')),
                                         engine)
        self.assertEqual(third[0][0][0], 'Otwarte okna')

    def test_the_switches_take_the_group_and_the_place_away(self):
        engine = _Engine({('TitanShell', 'GroupNames'): False,
                          ('TitanShell', 'Positions'): False})
        self.focus = self.bar.buttons[1]
        before, after = titan_shell.segments_for(
            titan_shell.read(_obj('Poczta')), engine)
        self.assertEqual(before, [])
        self.assertEqual([text for text, _ in after],
                         [L('titanShell.state.minimized')])

    def test_a_control_of_another_process_is_never_asked_about(self):
        self.focus = self.bar.buttons[1]
        obj = _obj('Poczta')
        obj.process_id = os.getpid() + 1
        self.assertIsNone(titan_shell.read(obj))

    def test_a_focus_that_has_moved_on_is_not_described(self):
        self.focus = self.bar.buttons[1]
        self.bar.buttons[1]._h = 55
        obj = _obj('Poczta')
        obj.hwnd = 77
        self.assertIsNone(titan_shell.read(obj))

    def test_no_shell_running_is_no_answer(self):
        self.shell._running = False
        self.focus = self.bar.buttons[1]
        self.assertIsNone(titan_shell.read(_obj('Poczta')))


class TheDesktopAndTheStartMenu(ShellTestCase):

    def test_a_desktop_icon_says_whether_it_is_a_folder_or_a_file(self):
        self.focus = self.desktop.list
        self.desktop.list.focused = 0
        info = titan_shell.read(_obj('Dokumenty', pos=1))
        self.assertEqual(info.surface, 'desktop')
        self.assertEqual(info.kind, L('titanShell.kind.folder'))
        self.desktop.list.focused = 1
        info = titan_shell.read(_obj('notatki', pos=2))
        self.assertEqual(info.kind, L('titanShell.kind.file'))
        self.assertEqual(info.position, (2, 2))

    def test_a_desktop_list_re_read_under_the_cursor_is_found_by_name(self):
        self.focus = self.desktop.list
        self.desktop.list.focused = -1
        info = titan_shell.read(_obj('notatki', pos=1))
        self.assertEqual(info.name, 'notatki')

    def test_a_start_menu_entry_says_what_it_starts(self):
        for kind, key in (('app', 'app'), ('game', 'game'),
                          ('macro', 'macro'), ('im_module', 'messenger'),
                          ('folder', 'branch')):
            self.focus = MenuTree(_Entry('X', kind))
            self.assertEqual(titan_shell.read(_obj('X')).kind,
                             L('titanShell.kind.' + key), kind)
        self.focus = MenuTree(_Entry('Uruchom', 'action'))
        self.assertEqual(titan_shell.read(_obj('Uruchom')).kind, '')

    def test_where_am_i_says_the_whole_of_it(self):
        self.focus = self.bar.buttons[1]
        text = titan_shell.where_am_i_text(titan_shell.read(_obj('Poczta')))
        for part in (L('titanShell.surface.taskbar'), 'Otwarte okna',
                     'Poczta', L('titanShell.kind.window'),
                     L('titanShell.state.minimized'),
                     L('element.positionOf', 2, 3)):
            self.assertIn(part, text)


class WindowsComingAndGoingBehindTheUser(ShellTestCase):

    def test_only_background_windows_by_default(self):
        before = {1: ('Notatnik', True), 2: ('Poczta', False)}
        after = {2: ('Poczta', False), 4: ('Pobrano', False),
                 5: ('Nowe', True)}
        self.assertEqual(titan_shell.changes(before, after, 'background'),
                         [('opened', 'Pobrano')])
        before = {1: ('Notatnik', False), 2: ('Poczta', True)}
        self.assertEqual(titan_shell.changes(before, {2: ('Poczta', True)},
                                             'background'),
                         [('closed', 'Notatnik')])
        self.assertEqual(titan_shell.changes(before, {}, 'all'),
                         [('closed', 'Notatnik'), ('closed', 'Poczta')])
        self.assertEqual(titan_shell.changes(before, {}, 'none'), [])

    def test_the_watch_reads_the_taskbars_own_list(self):
        engine = _Engine()
        watch = titan_shell.WindowWatch(engine)
        self.assertEqual(watch.tick(), [])          # the baseline
        self.bar._windows = self.bar._windows + [ShellWindow(9, 'Raport')]
        self.assertEqual(watch.tick(), [('opened', 'Raport')])
        self.assertEqual(engine.said,
                         [L('titanShell.event.opened', 'Raport')])
        self.bar._windows = [w for w in self.bar._windows if w.hwnd != 2]
        watch.tick()
        self.assertEqual(engine.said[-1], L('titanShell.event.closed', 'Poczta'))

    def test_switched_off_it_says_nothing(self):
        engine = _Engine({('TitanShell', 'WindowEvents'): 'none'})
        watch = titan_shell.WindowWatch(engine)
        watch.tick()
        self.bar._windows = []
        self.assertEqual(watch.tick(), [])
        self.assertEqual(engine.said, [])


class TheEngineReadsTheWindowTabLandsOn(ShellTestCase):
    """The taskbar's group announcement arrives as an override; the window
    the keyboard landed on used to be swallowed by it."""

    def _engine(self):
        engine = object.__new__(TitanAccessEngine)
        engine.settings = _Settings()
        engine.context = None
        engine.sound = None
        engine.speech = None
        engine.current_object = None
        engine._override_until = 0.0
        engine._state_suffix = None
        engine._role_label_override = None
        engine._muted_for_foreground = lambda: False
        engine._remember_toggle = lambda obj: None
        engine._dialog_kind_of = lambda obj: None
        engine._label_unnamed = lambda obj: None
        engine._auditory_icon = lambda obj: None
        engine._adapted = lambda obj: None
        engine._semantic_layers = lambda obj: ([], [])
        engine._shared_layers = lambda obj: []
        self.spoken = []
        engine.speak_segments = lambda segments, **_: self.spoken.append(
            [s[0] for s in segments])
        engine.speak = lambda text, **_: self.spoken.append([text])
        return engine

    def test_tab_into_open_windows_says_the_group_and_the_window(self):
        engine = self._engine()
        engine._override_until = 10 ** 10        # "Otwarte okna" was said
        self.focus = self.bar.buttons[1]
        engine.announce_object(_obj('Poczta'))
        words = self.spoken[-1]
        self.assertEqual(words[0], 'Otwarte okna')
        self.assertIn('Poczta', words)
        self.assertIn(L('titanShell.kind.window'), words)
        self.assertIn(L('titanShell.state.minimized'), words)

    def test_an_override_outside_the_shell_still_wins(self):
        engine = self._engine()
        engine._override_until = 10 ** 10
        self.focus = None
        engine.announce_object(_obj('Aplikacje'))
        self.assertEqual(self.spoken, [])

    def test_switched_off_the_override_is_honoured_as_before(self):
        engine = self._engine()
        engine.settings = _Settings({('TitanShell', 'Semantics'): False})
        engine._override_until = 10 ** 10
        self.focus = self.bar.buttons[1]
        engine.announce_object(_obj('Poczta'))
        self.assertEqual(self.spoken, [])


class AgainstTheRealShellClasses(unittest.TestCase):
    """The attribute names read above are the shell's REAL ones: the real
    controls are built in a frame that is never shown, and the shell is
    never started."""

    @classmethod
    def setUpClass(cls):
        try:
            import wx
            sys.path.insert(0, ROOT)
            from src.shell import taskbar, win_shell     # noqa: F401
            from src.ui import start_menu_content        # noqa: F401
        except Exception as error:                       # noqa: BLE001
            raise unittest.SkipTest('no wx or no shell: %s' % error)
        cls.wx = wx
        cls.app = wx.App(False)
        cls.frame = wx.Frame(None)

    @classmethod
    def tearDownClass(cls):
        cls.frame.Destroy()

    def test_a_real_window_button_and_tray_icon(self):
        from src.shell import taskbar, win_shell
        bar = types.SimpleNamespace(refresh_windows=lambda: None,
                                    show_hidden_tray_icons=lambda: None)
        window = win_shell.ShellWindow(0, 'Poczta', minimized=True)
        button = taskbar.TaskButton(self.frame, window, bar)
        icon = types.SimpleNamespace(text='Bateria', hidden=True,
                                     chevron=False, icon_handle=lambda: 0)
        tray = taskbar.TrayIconButton(self.frame, icon, bar)
        groups = [('tasks', [button]), ('tray', [tray])]
        bar._group_of = lambda control: next(
            ((i, n, c) for i, (n, c) in enumerate(groups) if control in c),
            (-1, '', []))
        info = titan_shell.describe_taskbar_control(bar, button)
        self.assertEqual(info.kind, L('titanShell.kind.window'))
        self.assertEqual(info.states, [L('titanShell.state.minimized')])
        self.assertEqual(info.group, taskbar.group_label('tasks'))
        self.assertEqual(info.name, 'Poczta')
        info = titan_shell.describe_taskbar_control(bar, tray)
        self.assertEqual(info.states, [L('titanShell.state.hidden')])

    def test_a_real_start_menu_tree(self):
        from src.ui.start_menu_content import MenuEntry, MenuTree
        tree = MenuTree(self.frame, None, lambda entry: [], self.wx.WHITE,
                        self.wx.BLACK, 'Menu')
        tree.set_entries([MenuEntry('Notatki', 'app', payload='tNotes'),
                          MenuEntry('Gry', 'folder')])
        names = titan_shell._class_names(tree)
        self.assertIn('MenuTree', names)
        info = titan_shell.describe_menu_entry(tree, names)
        self.assertEqual(info.kind, L('titanShell.kind.app'))
        self.assertEqual(info.name, 'Notatki')


if __name__ == '__main__':
    unittest.main()
