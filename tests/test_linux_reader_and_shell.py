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




# --------------------------------------------------------------------------- #
# A fake Atspi, enough for the provider, the presenter and the tracker
# --------------------------------------------------------------------------- #
class _Enum(int):
    _names = {}

    def __new__(cls, value, name):
        obj = int.__new__(cls, value)
        obj.name = name
        return obj


class _Roles:
    _order = ['INVALID', 'FRAME', 'WINDOW', 'DIALOG', 'ALERT', 'FILE_CHOOSER',
              'COLOR_CHOOSER', 'FONT_CHOOSER', 'PANEL', 'GROUPING', 'FILLER',
              'SCROLL_PANE', 'LIST', 'LIST_BOX', 'LIST_ITEM', 'TABLE', 'TABLE_ROW',
              'TABLE_CELL', 'TABLE_COLUMN_HEADER', 'TABLE_ROW_HEADER', 'TREE',
              'TREE_TABLE', 'TREE_ITEM', 'MENU', 'MENU_BAR', 'MENU_ITEM',
              'CHECK_MENU_ITEM', 'RADIO_MENU_ITEM', 'PAGE_TAB', 'PAGE_TAB_LIST',
              'PUSH_BUTTON', 'TOGGLE_BUTTON', 'LABEL', 'STATIC', 'TEXT', 'ENTRY',
              'PASSWORD_TEXT', 'CHECK_BOX', 'RADIO_BUTTON', 'COMBO_BOX',
              'TOOL_BAR', 'STATUS_BAR', 'APPLICATION', 'SEPARATOR', 'SLIDER',
              'SPIN_BUTTON', 'PROGRESS_BAR', 'SCROLL_BAR', 'LINK', 'HEADING',
              'IMAGE', 'ICON', 'DOCUMENT_FRAME', 'DOCUMENT_TEXT', 'DOCUMENT_WEB',
              'DOCUMENT_EMAIL', 'VIEWPORT', 'SPLIT_PANE', 'LAYERED_PANE', 'ROOT_PANE',
              'GLASS_PANE', 'INTERNAL_FRAME', 'TOOL_TIP', 'DESKTOP_FRAME', 'UNKNOWN',
              'CANVAS']

    def __init__(self):
        for i, name in enumerate(self._order):
            setattr(self, name, _Enum(i, name))


class _States:
    _order = ['INVALID', 'FOCUSED', 'CHECKABLE', 'CHECKED', 'INDETERMINATE',
              'EXPANDABLE', 'EXPANDED', 'SELECTED', 'ENABLED', 'SENSITIVE',
              'EDITABLE', 'REQUIRED', 'PRESSED', 'BUSY', 'HAS_POPUP', 'ACTIVE',
              'SHOWING', 'MODAL', 'VISIBLE', 'ICONIFIED', 'FOCUSABLE', 'SELECTABLE']

    def __init__(self):
        for i, name in enumerate(self._order):
            setattr(self, name, _Enum(i, name))


class _Relation:
    def __init__(self, kind): self._kind = kind
    def get_relation_type(self): return self._kind


class _StateSet:
    def __init__(self, states):
        self._states = set(states)

    def contains(self, state):
        return state in self._states


class _Node:
    """One fake Atspi.Accessible."""

    def __init__(self, role, name='', states=(), children=(), text=None):
        self._role, self._name, self._states = role, name, list(states)
        self.children = list(children)
        self.parent = None
        self.text = text
        self.selected = []            # indices
        self.done = []
        for child in self.children:
            child.parent = self

    # Accessible
    def get_role(self): return self._role
    def get_role_name(self): return self._role.name.lower().replace('_', ' ')
    def get_name(self): return self._name
    def get_description(self): return ''
    def get_state_set(self): return _StateSet(self._states)
    def get_parent(self): return self.parent
    def get_child_count(self): return len(self.children)
    def get_child_at_index(self, i): return self.children[i]
    def get_index_in_parent(self):
        return self.parent.children.index(self) if self.parent else 0
    def get_process_id(self): return 4321
    def get_application(self):
        node = self
        while node.parent is not None:
            node = node.parent
        return node
    def get_attributes(self): return {}
    def get_relation_set(self): return list(getattr(self, 'relations', []))
    # interfaces answered by the object itself, as libatspi does
    def get_text_iface(self): return self if self.text is not None else None
    def get_character_count(self): return len(self.text or '')
    def get_text(self, a, b): return (self.text or '')[a:b]
    def get_value_iface(self): return None
    def get_component_iface(self): return self
    def get_extents(self, _coord):
        class R: x, y, width, height = 10, 20, 100, 30
        return R()
    def get_selection_iface(self): return self
    def get_n_selected_children(self): return len(self.selected)
    def get_selected_child(self, i): return self.children[self.selected[i]]


class _Event:
    def __init__(self, type_, source, detail1=0, any_data=None):
        self.type, self.source, self.detail1, self.detail2 = type_, source, detail1, 0
        self.any_data = any_data


class _FakeAtspi:
    def __init__(self):
        self.Role = _Roles()
        self.StateType = _States()
        self.registered = []
        self.contexts = []
        fake = self

        class EventListener:
            @staticmethod
            def new(handler):
                return handler

            @staticmethod
            def register(listener, name):
                fake.registered.append((listener, name))
                return True

            @staticmethod
            def deregister(listener, name):
                return True
        self.EventListener = EventListener

        class CoordType:
            SCREEN = 0
        self.CoordType = CoordType

        class RelationType:
            LABEL_FOR, LABELLED_BY = 'label-for', 'labelled-by'
        self.RelationType = RelationType

    def init(self): return 0
    def set_main_context(self, ctx): self.contexts.append(ctx)
    def get_desktop(self, _i): return _Node(self.Role.INVALID)

    def fire(self, name, source, detail1=0, any_data=None):
        for listener, registered in self.registered:
            if registered == name:
                listener(_Event(name, source, detail1, any_data))


def _install_fake():
    from titan_access import atspi_focus
    fake = _FakeAtspi()
    atspi_focus._Atspi = fake
    atspi_focus._roles = None
    return fake, atspi_focus


class TheProviderHearsARowMoveWithoutAFocusEvent(unittest.TestCase):
    """Measured on a wx window in WSLg: Down in a list is
    ``object:selection-changed`` on the TABLE, nothing on the cell; F10 is
    ``object:state-changed:selected`` on the menu; a toolkit that does say
    which row sends ``object:active-descendant-changed``. Each has to reach
    the engine as a focus, or the reader says nothing about any of them."""

    def setUp(self):
        self.fake, self.mod = _install_fake()
        R, S = self.fake.Role, self.fake.StateType
        self.cells = [_Node(R.TABLE_CELL, 'File Manager'), _Node(R.TABLE_CELL, 'Notes'),
                      _Node(R.TABLE_CELL, 'Text Editor')]
        self.table = _Node(R.TABLE, 'Lista aplikacji', [S.FOCUSED, S.ENABLED, S.SENSITIVE],
                           self.cells)
        self.app = _Node(R.APPLICATION, 'main.py', children=[
            _Node(R.FRAME, 'Titan', [S.ACTIVE, S.SHOWING], [self.table])])
        self.heard = []
        self.provider = self.mod.AtspiProvider()
        self.provider.add_focus_listener(self.heard.append)
        self.assertTrue(self.provider.start())

    def tearDown(self):
        self.mod._Atspi = None
        self.mod._roles = None

    def test_the_events_it_listens_for(self):
        names = {name for _l, name in self.fake.registered}
        for wanted in ('object:state-changed:focused', 'focus:',
                       'object:state-changed:selected', 'object:selection-changed',
                       'object:active-descendant-changed'):
            self.assertIn(wanted, names)

    def test_a_selection_change_in_the_focused_table_is_the_row(self):
        self.table.selected = [1]
        self.fake.fire('object:selection-changed', self.table)
        self.assertEqual([o.name for o in self.heard], ['Notes'])
        # A cell of a one-column table (or of one that answers no columns,
        # as a GtkTreeView mid-rebuild does) is a list item to the user.
        self.assertEqual(self.heard[0].role, 'listitem')
        self.assertEqual((self.heard[0].pos_in_set, self.heard[0].size_of_set), (2, 3))

    def test_the_same_row_twice_in_a_blink_is_said_once(self):
        self.table.selected = [2]
        self.fake.fire('object:state-changed:selected', self.cells[2], 1)
        self.fake.fire('object:selection-changed', self.table)
        self.assertEqual([o.name for o in self.heard], ['Text Editor'])

    def test_a_list_reselecting_its_own_row_is_not_the_user_moving(self):
        import time
        self.table.selected = [1]
        self.fake.fire('object:selection-changed', self.table)
        time.sleep(0.35)
        self.fake.fire('object:selection-changed', self.table)      # a refresh, same row
        self.assertEqual([o.name for o in self.heard], ['Notes'])
        self.table.selected = [2]
        self.fake.fire('object:selection-changed', self.table)      # a different row
        self.assertEqual([o.name for o in self.heard], ['Notes', 'Text Editor'])

    def test_a_selection_in_a_table_nobody_is_on_is_not_news(self):
        R, S = self.fake.Role, self.fake.StateType
        clock = _Node(R.TABLE_CELL, 'Zegar: 08:10')
        status = _Node(R.TABLE, 'Pasek stanu', [S.ENABLED], [clock])
        self.app.children[0].children.append(status)
        status.parent = self.app.children[0]
        status.selected = [0]
        self.fake.fire('object:selection-changed', status)
        self.fake.fire('object:state-changed:selected', clock, 1)
        self.assertEqual(self.heard, [])

    def test_a_menu_opening_is_the_menu(self):
        R = self.fake.Role
        item = _Node(R.MENU_ITEM, 'Settings')
        menu = _Node(R.MENU, 'Program', children=[item])
        bar = _Node(R.MENU_BAR, '', children=[menu])
        self.app.children[0].children.append(bar)
        bar.parent = self.app.children[0]
        self.fake.fire('object:state-changed:selected', menu, 1)
        dropdown = _Node(R.MENU, '', children=[])
        menu.children.append(dropdown); dropdown.parent = menu
        self.fake.fire('object:state-changed:selected', dropdown, 1)   # the popup itself: nothing
        self.fake.fire('object:state-changed:selected', item, 1)
        self.assertEqual([o.name for o in self.heard], ['Program', 'Settings'])
        self.assertEqual([o.role for o in self.heard], ['menu', 'menuitem'])

    def test_an_active_descendant_is_the_child_it_carries(self):
        self.fake.fire('object:active-descendant-changed', self.table, 2,
                       any_data=self.cells[0])
        self.assertEqual([o.name for o in self.heard], ['File Manager'])

    def test_a_table_taking_the_focus_reads_as_its_row(self):
        self.table.selected = [0]
        self.fake.fire('object:state-changed:focused', self.table, 1)
        self.assertEqual([o.name for o in self.heard], ['File Manager'])

    def test_a_nameless_button_is_called_by_its_description(self):
        R = self.fake.Role
        icon = _Node(R.PUSH_BUTTON, '', children=[]); icon._states = []
        icon.get_description = lambda: 'Open your personal folder'
        self.app.children[0].children.append(icon); icon.parent = self.app.children[0]
        self.fake.fire('object:state-changed:focused', icon, 1)
        self.assertEqual([o.name for o in self.heard], ['Open your personal folder'])

    def test_a_nautilus_icon_is_a_row_and_not_unavailable(self):
        R, S = self.fake.Role, self.fake.StateType
        files = [_Node(R.CANVAS, 'Dokumenty', [S.FOCUSABLE]), _Node(R.CANVAS, 'notatka.txt', [S.FOCUSABLE])]
        view = _Node(R.LAYERED_PANE, 'Icon View', [S.FOCUSABLE, S.ENABLED, S.SENSITIVE], files)
        self.app.children[0].children.append(view); view.parent = self.app.children[0]
        self.fake.fire('object:state-changed:focused', files[1], 1)
        obj = self.heard[-1]
        self.assertEqual((obj.name, obj.role, obj.pos_in_set, obj.size_of_set), ('notatka.txt', 'listitem', 2, 2))
        self.assertNotIn('unavailable', obj.states)
        button = _Node(R.PUSH_BUTTON, 'Greyed', [])
        self.assertIn('unavailable', self.mod.to_object(button).states)

    def test_focus_leaving_is_nothing(self):
        self.fake.fire('object:state-changed:focused', self.table, 0)
        self.assertEqual(self.heard, [])


class TheKeystrokeRegistrationReplyIsAdvisory(unittest.TestCase):
    """at-spi2-core 2.38's registry adds the listener, tells every
    application, and then ``return FALSE``s. Measured: 28 keys delivered to
    a listener the bus had refused. So a registration that did not raise
    is one, the listener is non-global (served by the application's own
    ATK bridge, which a Wayland session and WSLg both have), and the
    reader does not fall back to a listener that cannot consume."""

    def setUp(self):
        self.fake, self.focus = _install_fake()
        from titan_access import atspi_keys
        self.keys = atspi_keys
        self.old_linux = atspi_keys.IS_LINUX
        atspi_keys.IS_LINUX = True
        atspi_keys._registered.clear()
        atspi_keys._replies.update(yes=0, no=0)
        self.calls = []
        fake = self.fake

        class S(int):
            pass

        class SyncType:
            SYNCHRONOUS, CANCONSUME, ALL_WINDOWS, NOSYNC = 1, 2, 4, 0

            def __new__(cls, v):
                return S(v)
        fake.KeyListenerSyncType = SyncType

        class DeviceListener:
            @staticmethod
            def new(cb):
                return cb
        fake.DeviceListener = DeviceListener
        fake.EventType = type('ET', (), {'KEY_PRESSED_EVENT': 1, 'KEY_RELEASED_EVENT': 2})
        calls = self.calls

        def register(listener, keys, mask, types, sync):
            calls.append((mask, int(sync)))
            return False
        fake.register_keystroke_listener = register
        fake.deregister_keystroke_listener = lambda *a: True

    def tearDown(self):
        self.keys.IS_LINUX = self.old_linux
        self.keys._registered.clear()
        self.keys._listener = None
        self.focus._Atspi = None

    def test_every_mask_is_registered_non_global_and_kept_despite_no(self):
        class Hook:
            def _process(self, *a):
                return False
        self.assertTrue(self.keys.start(Hook()))
        self.assertEqual(len(self.calls), 256)
        self.assertEqual({sync for _m, sync in self.calls}, {3})      # SYNCHRONOUS|CANCONSUME
        report = self.keys.registration_report()
        self.assertEqual(report['masks'], 256)
        self.assertEqual(report['answered_no'], 256)
        self.assertFalse(report['pynput'])

    def test_a_key_the_hook_takes_is_consumed(self):
        taken = []

        class Hook:
            def _process(self, vk, scan, flags, is_down):
                taken.append((vk, flags, is_down))
                return vk == 0x2D                                       # Insert
        self.keys.start(Hook())
        listener = self.keys._listener
        ev = type('E', (), {'type': 1, 'id': 0xff63, 'hw_code': 118})
        self.assertTrue(listener(ev))
        ev2 = type('E', (), {'type': 2, 'id': 0xff54, 'hw_code': 116})   # Down up
        self.assertFalse(listener(ev2))
        self.assertEqual(taken, [(0x2D, 0x01, True), (0x28, 0x81, False)])


class TheContextIsWalkedOverAtspi(unittest.TestCase):
    """The presenter asked every node UIA questions (ControlTypeName,
    GetParentControl); an Atspi.Accessible answers AttributeError to both,
    so no dialog, group or list was ever announced on Linux."""

    def setUp(self):
        self.fake, self.focus = _install_fake()
        R, S = self.fake.Role, self.fake.StateType
        self.ok = _Node(R.PUSH_BUTTON, 'OK', [S.FOCUSED, S.ENABLED, S.SENSITIVE])
        self.body = _Node(R.LABEL, 'The file could not be saved.')
        self.dialog = _Node(R.ALERT, 'Information', [S.ACTIVE, S.MODAL, S.SHOWING],
                            [_Node(R.FILLER, '', children=[self.body, self.ok])])
        self.app = _Node(R.APPLICATION, 'main.py', children=[self.dialog])
        from titan_access import context_presenter
        self.cp = context_presenter

        class Settings:
            def get_bool(self, *_a, **_k):
                return True

        class Engine:
            settings = Settings()

            def _is_tce_foreground(self):
                return False

            def consume_dialog_kind(self):
                return None

            def play(self, *_a):
                pass
        self.presenter = context_presenter.ContextPresenter(Engine())

    def tearDown(self):
        self.focus._Atspi = None

    def test_a_dialog_is_its_title_its_kind_and_its_message_once(self):
        R = self.fake.Role
        # A label that names a field is the field's, not the message's.
        field_label = _Node(R.LABEL, 'Name:'); field_label.relations = [_Relation('label-for')]
        self.dialog.children[0].children.insert(0, field_label); field_label.parent = self.dialog.children[0]
        obj = self.focus.to_object(self.ok)
        segs = self.presenter.context_segments(obj)
        texts = [t for t, _p in segs]
        self.assertTrue(texts and 'Information' in texts[0], texts)
        self.assertIn('The file could not be saved.', texts)
        self.assertFalse(any('Name:' in t for t in texts), texts)
        # The second focus inside the same dialog says nothing again.
        self.assertEqual(self.presenter.context_segments(obj), [])

    def test_a_named_group_and_a_list_are_said_a_nameless_panel_is_not(self):
        R, S = self.fake.Role, self.fake.StateType
        row = _Node(R.LIST_ITEM, 'Row', [S.FOCUSED])
        lst = _Node(R.LIST, 'Options', children=[row])
        group = _Node(R.PANEL, 'Sounds', children=[lst])
        notebook = _Node(R.PAGE_TAB_LIST, '', children=[group])       # gedit's editor sits in one
        layout = _Node(R.PANEL, '', children=[notebook])
        frame = _Node(R.FRAME, 'Settings', [S.ACTIVE], [layout])
        _Node(R.APPLICATION, 'main.py', children=[frame])
        texts = [t for t, _p in self.presenter.context_segments(self.focus.to_object(row))]
        self.assertTrue(any('Settings' in t for t in texts), texts)
        self.assertTrue(any('Options' in t for t in texts), texts)
        self.assertTrue(any('Sounds' in t for t in texts), texts)
        self.assertFalse(any(t.strip() in ('group', 'grupa') for t in texts), texts)
        from titan_access.localization import role_label
        self.assertNotIn(role_label('tabcontrol'), texts)             # a nameless notebook is furniture


class TheMenuTrackerWalksAnAtspiMenu(unittest.TestCase):

    def setUp(self):
        self.fake, self.focus = _install_fake()
        R = self.fake.Role
        self.items = [_Node(R.MENU_ITEM, 'Install'), _Node(R.SEPARATOR),
                      _Node(R.MENU_ITEM, 'Settings'), _Node(R.MENU, 'More')]
        self.menu = _Node(R.MENU, 'Program', children=self.items)
        self.bar = _Node(R.MENU_BAR, '', children=[self.menu])
        _Node(R.APPLICATION, 'main.py', children=[_Node(R.FRAME, 'Titan', children=[self.bar])])
        from titan_access import menu_tracker
        self.T = menu_tracker.MenuTracker

    def tearDown(self):
        self.focus._Atspi = None

    def test_the_tree_questions_have_atspi_answers(self):
        # Everything under a GTK menu bar has the bar as an ancestor: an item
        # of the dropdown is in THAT menu, the top-level menu is on the bar.
        self.assertFalse(self.T._in_menu_bar(self.items[0]))
        self.assertTrue(self.T._in_menu_bar(self.menu))
        self.assertTrue(self.T._is_top_level_menu(self.menu))
        self.assertFalse(self.T._is_top_level_menu(self.items[3]))
        self.assertIs(self.T._menu_parent(self.items[2]), self.menu)
        self.assertIsNone(self.T._menu_parent(self.menu))     # a top-level menu is on the bar
        self.assertEqual(self.T._name(self.menu), 'Program')
        self.assertEqual(self.T._count_items(self.menu), 3)   # the separator is not an item
        self.assertEqual(self.T._menu_id(self.menu), self.T._menu_id(self.menu))
        self.assertNotEqual(self.T._menu_id(self.menu), self.T._menu_id(self.items[3]))


class TheReaderSpeaksTheLanguagesVoiceByDefault(unittest.TestCase):
    """eSpeak lists 170 voices alphabetically; "the first" was Afrikaans."""

    def test_the_voice_of_titans_language_is_chosen(self):
        from src.titan_core.tce_speech import default_voice_index
        voices = [{'id': 'af', 'display_name': 'Afrikaans (Male)'},
                  {'id': 'en-gb', 'display_name': 'English (Great Britain)'},
                  {'id': 'pl', 'display_name': 'Polish'},
                  {'id': 'pl+f3', 'display_name': 'Polish (Female 3)'}]
        self.assertEqual(default_voice_index(voices, 'pl'), 2)
        self.assertEqual(default_voice_index(voices, 'en'), 1)
        self.assertEqual(default_voice_index(voices, 'en_GB'), 1)
        self.assertEqual(default_voice_index(voices, 'xx'), 0)
        self.assertEqual(default_voice_index([], 'pl'), 0)
        self.assertEqual(default_voice_index(['Zosia', 'Polish voice'], 'pl'), 1)


class _TextNode(_Node):
    """A fake control with the Atspi.Text interface."""

    def __init__(self, role, name, body, caret=0):
        _Node.__init__(self, role, name, text=body)
        self.caret = caret
        self.sel = None

    def get_caret_offset(self): return self.caret
    def set_caret_offset(self, offset): self.caret = offset; return True
    def get_n_selections(self): return 1 if self.sel else 0
    def get_selection(self, _i):
        class S: pass
        s = S(); s.start_offset, s.end_offset = self.sel; return s

    def get_string_at_offset(self, offset, gran):
        body = self.text
        class R: pass
        r = R()
        if gran == 'CHAR':
            r.content, r.start_offset, r.end_offset = body[offset:offset + 1], offset, offset + 1
            return r
        if gran == 'WORD':
            start = offset
            while start > 0 and not body[start - 1].isspace(): start -= 1
            end = offset
            while end < len(body) and not body[end].isspace(): end += 1
            r.content, r.start_offset, r.end_offset = body[start:end], start, end
            return r
        start = body.rfind('\n', 0, offset) + 1
        end = body.find('\n', offset)
        end = len(body) if end < 0 else end + 1
        r.content, r.start_offset, r.end_offset = body[start:end], start, end
        return r


class TheTreeIsSteppedOverAtspi(unittest.TestCase):
    """Object navigation (Insert+NumPad), the walked lists' `children` and
    `parent`, Enter on an object: every one asked UIA questions of an
    Atspi.Accessible and answered nothing on Linux."""

    def setUp(self):
        self.fake, self.focus = _install_fake()
        R, S = self.fake.Role, self.fake.StateType
        self.fake.TextGranularity = type('TG', (), {'CHAR': 'CHAR', 'WORD': 'WORD', 'LINE': 'LINE'})
        self.fake.KeySynthType = type('KS', (), {'SYM': 0})
        self.fake.generate_keyboard_event = lambda *a: True
        vis = [S.SHOWING, S.VISIBLE]
        self.save = _Node(R.PUSH_BUTTON, 'Save', vis)
        self.ask = _Node(R.PUSH_BUTTON, 'Ask', vis)
        self.row = _Node(R.LIST_ITEM, 'Apple', vis)
        self.lst = _Node(R.LIST, 'Fruit', vis, [self.row, _Node(R.LIST_ITEM, 'Pear', vis)])
        self.text = _TextNode(R.TEXT, 'Note', 'Ala ma kota.\nDrugi wiersz.', caret=4)
        self.text._states = vis
        buttons = _Node(R.PANEL, '', vis, [self.save, self.ask])
        self.group = _Node(R.PANEL, 'Options', vis, [_Node(R.CHECK_BOX, 'Tick', vis)])
        layout = _Node(R.FILLER, '', vis, [self.lst, self.text, self.group, buttons])
        self.frame = _Node(R.FRAME, 'Probe', vis + [S.ACTIVE], [layout])
        _Node(R.APPLICATION, 'probe', children=[self.frame])

    def tearDown(self):
        self.focus._Atspi = None

    def test_simple_review_steps_past_layout(self):
        f = self.focus
        self.assertIs(f.simple_step(self.lst, 'next'), self.text)
        self.assertIs(f.simple_step(self.text, 'next'), self.group)
        self.assertIs(f.simple_step(self.group, 'next'), self.save)   # the nameless panel is stepped over
        self.assertIs(f.simple_step(self.save, 'prev'), self.group)
        self.assertIs(f.simple_step(self.row, 'parent'), self.lst)
        self.assertIs(f.simple_step(self.lst, 'child'), self.row)
        self.assertIs(f.simple_step(self.save, 'parent'), self.frame) # the filler is layout
        self.assertIsNone(f.simple_step(self.ask, 'next'))
        self.assertTrue(f.is_top(self.frame))

    def test_object_navigation_uses_it(self):
        from titan_access import object_nav
        nav = object_nav.ObjectNavigator.__new__(object_nav.ObjectNavigator)

        class Engine:
            settings = type('S', (), {'get_bool': staticmethod(lambda *a, **k: True)})()
        nav.engine = Engine()
        self.assertIs(nav._step(self.lst, 'next'), self.text)
        self.assertIs(nav._step(self.save, 'parent'), self.frame)      # a titled window is a place
        self.assertIsNone(nav._step(self.frame, 'parent'))             # and the top of the walk
        self.frame._name = ''
        self.assertIsNone(nav._step(self.save, 'parent'))              # a nameless one is the boundary

    def test_a_child_gtk_cannot_index_is_still_stepped_past(self):
        # GTK answers -1 for some objects' index in parent; "-1 + 1" was the
        # object itself, so Next from a text view read the text view again.
        self.text.get_index_in_parent = lambda: -1
        self.assertEqual(self.focus.index_of(self.text), 1)
        self.assertIs(self.focus.sibling_of(self.text, 1), self.group)
        self.assertIs(self.focus.simple_step(self.text, 'next'), self.group)

    def test_the_adapted_object_walks_the_tree(self):
        from titan_access import nvda_shape
        provider = self.focus.AtspiProvider()
        adapted = nvda_shape.Adapted(self.focus.to_object(self.lst), provider)
        self.assertEqual([c.name for c in adapted.children], ['Apple', 'Pear'])
        self.assertEqual(adapted.children[0].parent.name, 'Fruit')
        self.assertEqual(adapted.actionCount, 0)

    def test_the_text_interface_answers_caret_word_and_line(self):
        t = self.focus.TextOf.of(self.text)
        self.assertEqual(t.caret(), 4)
        self.assertEqual(t.unit(4, 'char')[0], 'm')
        self.assertEqual(t.unit(4, 'word')[0], 'ma')
        self.assertEqual(t.unit(14, 'line')[0], 'Drugi wiersz.')
        self.text.sel = (0, 3)
        self.assertEqual(t.selection(), 'Ala')
        self.assertIsNone(self.focus.TextOf.of(self.save))

    def test_the_editable_handler_reads_through_it(self):
        from titan_access import editable_text
        h = editable_text.EditableTextHandler.__new__(editable_text.EditableTextHandler)
        said = []

        class Engine:
            settings = type('S', (), {'phonetic_letters': False, 'announce_text_bounds': False})()
            def speak(self, text, **_k): said.append(text)
            def play(self, *_a): pass
        h.engine = Engine(); h._review = None; h._review_owner = None; h._last_caret = None
        h._last_win32_pos = None; h._last_spoken = ('', '', 0.0)
        h.engine.current_object = self.focus.to_object(self.text)
        h.set_element(h.engine.current_object)
        h.read_current_word(); self.assertEqual(said[-1], 'ma')
        h.navigate_word(True); self.assertEqual(said[-1], 'kota.')
        h.navigate_line(True); self.assertEqual(said[-1], 'Drugi wiersz.')
        h.read_selection(); self.assertTrue(said[-1])


class ScanModesOwnMoveIsNotReadTwice(unittest.TestCase):
    """Scan mode moves the real focus onto the node it announces; the focus
    event that fires comes back through the provider. Measured on Linux:
    every row read twice. The focus scan mode caused is recognised and
    the engine does not announce it again; one the user moved is."""

    def _handler(self):
        from titan_access import browse_mode
        import threading, types
        h = browse_mode.BrowseModeHandler.__new__(browse_mode.BrowseModeHandler)
        h._scan = True
        h._scan_hwnd = 0
        h._lock = threading.Lock()
        node = types.SimpleNamespace(name='Dźwięk', role='listitem')
        h._doc = types.SimpleNamespace(nodes=[types.SimpleNamespace(name='Ogólne', role='listitem'), node])
        h._index = 0
        h._char_pos = 0
        return h, node

    def setUp(self):
        from titan_access import browse_mode
        self._old_fg = browse_mode.vbuf.foreground_hwnd
        browse_mode.vbuf.foreground_hwnd = lambda: 0

    def tearDown(self):
        from titan_access import browse_mode
        browse_mode.vbuf.foreground_hwnd = self._old_fg   # a patch left behind is every later test's

    def test_the_focus_scan_mode_caused_is_its_own(self):
        import time, types
        h, node = self._handler()
        h._scan_moved = (node.name, node.role, time.time())
        obj = types.SimpleNamespace(name='Dźwięk', role='listitem')
        self.assertTrue(h.update_for_focus(obj))
        self.assertEqual(h._index, 1)
        # A second focus on the same row is the user's (Tab back), and is said.
        self.assertFalse(h.update_for_focus(obj))

    def test_a_focus_the_user_moved_is_announced(self):
        import types
        h, node = self._handler()
        self.assertFalse(h.update_for_focus(types.SimpleNamespace(name='Ogólne', role='listitem')))


class LocalOcrIsTitansModelOffWindows(unittest.TestCase):
    """`portable/localOcr` is NVDA's Windows recogniser; off Windows every
    caller of it - the virtual window's picture fallback, scan mode's OCR
    tier, the watcher - is answered by Titan's own model instead."""

    def setUp(self):
        from titan_access.portable import localOcr
        self.m = localOcr
        self.old = (localOcr._IS_WINDOWS, localOcr.model_available, localOcr.read_window_model)
        localOcr._IS_WINDOWS = False
        self.asked = []
        localOcr.model_available = lambda timeout=8.0: (True, '')
        localOcr.read_window_model = lambda hwnd, timeout=30.0: (self.asked.append(hwnd), localOcr.Reading(
            [[{'text': 'Zapisz', 'left': 10, 'top': 20, 'width': 60, 'height': 18}]]))[1]

    def tearDown(self):
        self.m._IS_WINDOWS, self.m.model_available, self.m.read_window_model = self.old

    def test_available_and_reading_go_to_the_model(self):
        self.assertEqual(self.m.available(), (True, ''))
        reading = self.m.read_window(1)
        self.assertEqual(reading.text if hasattr(reading, 'text') else None, 'Zapisz')
        self.assertEqual(self.m.read(0, 0, 100, 100, hwnd=1).lines[0][0]['text'], 'Zapisz')
        self.assertEqual(self.asked, [1, 1])


class TheLinuxDocumentFallsBackToAPicture(unittest.TestCase):

    def test_the_ocr_tier_is_asked_when_the_tree_says_nothing(self):
        from titan_access import virtual_buffer as vbuf
        fake, focus = _install_fake()
        R, S = fake.Role, fake.StateType
        frame = _Node(R.FRAME, 'Game', [S.ACTIVE, S.SHOWING])
        app = _Node(R.APPLICATION, 'game', children=[frame])
        desktop = _Node(R.DESKTOP_FRAME, 'main', children=[app])
        fake.get_desktop = lambda _i: desktop
        old = (vbuf.build_atspi, vbuf.build_ocr)
        vbuf.build_atspi = lambda window, limit=3000: []
        vbuf.build_ocr = lambda hwnd, on_status=None: [
            vbuf.VNode(name='Start', role='button'), vbuf.VNode(name='Quit', role='button')]
        try:
            doc = vbuf._build_for_window_atspi(True, None, None)
            self.assertEqual((doc.source, [n.name for n in doc.nodes]), ('ocr', ['Start', 'Quit']))
            doc = vbuf._build_for_window_atspi(False, None, None)
            self.assertEqual(doc.nodes, [])                       # not without being asked
            # A game is not on the accessibility bus at all: no window,
            # and still a picture to read.
            fake.get_desktop = lambda _i: _Node(R.DESKTOP_FRAME, 'main')
            doc = vbuf._build_for_window_atspi(True, None, None)
            self.assertEqual((doc.source, len(doc.nodes)), ('ocr', 2))
            self.assertEqual(vbuf.foreground_hwnd(), vbuf.ATSPI_WINDOW_TOKEN)
        finally:
            vbuf.build_atspi, vbuf.build_ocr = old
            focus._Atspi = None


class WhatTheReaderSaidIsWrittenDown(unittest.TestCase):

    def test_the_last_utterances_are_kept(self):
        from titan_access import speech_adapter as sa
        before = len(sa.spoken())
        sa._SPOKEN.append('hello')
        self.assertEqual(sa.spoken()[-1], 'hello')
        self.assertLessEqual(len(sa.spoken()), 20)
        self.assertGreaterEqual(len(sa.spoken()), min(before + 1, 20))


if __name__ == '__main__':
    unittest.main(verbosity=2)
