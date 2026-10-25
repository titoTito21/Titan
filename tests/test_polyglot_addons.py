# -*- coding: utf-8 -*-
"""Polyglot: every kind of Titan add-on in another language, through
Titan's REAL loaders.

Run directly: ``python tests/test_polyglot_addons.py``. APPDATA is a
temporary folder (the examples are installed into its overlay), Titan's
speech and every dialog are replaced by recorders, and the objects that would
make a sound or press a key (a Titan IM module's ``sounds``, the gamepad
helpers) are replaced too. Nothing is shown, spoken or pressed.
"""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(ROOT, 'data', 'components', 'polyglot')
_APPDATA = tempfile.mkdtemp(prefix='polyglot_addons_')
os.environ['APPDATA'] = _APPDATA
os.environ['TITAN_LANGUAGE'] = 'en'
sys.path[:0] = [COMPONENT, ROOT]

import wx  # noqa: E402

_APP = wx.App(False)

from polyglotkit import adapters, stubs, runtimes  # noqa: E402
from polyglotkit.api import TitanAPI               # noqa: E402

SPOKEN = []
ANSWERS = []
ACTIONS = []


class _Result(object):
    ok = True
    text = 'done'


def _titan_call(addon, action, **args):
    ACTIONS.append((addon, action, args))
    if (addon, action) == ('titan', 'speak'):
        SPOKEN.append(args.get('text'))
    return _Result()


adapters._titan_call = _titan_call


def _answer(*_args, **_kwargs):
    return ANSWERS.pop(0) if ANSWERS else None


TitanAPI.ask = lambda self, *a, **k: _answer()
TitanAPI.choose = lambda self, *a, **k: _answer()
TitanAPI.confirm = lambda self, *a, **k: bool(_answer())
TitanAPI.message = lambda self, text, title=None: SPOKEN.append(str(text)) or True
TitanAPI.speak = lambda self, text, *a, **k: SPOKEN.append(str(text)) or True


class Recorder(object):
    """Every method called on it is written down."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith('_') or name == 'as_dict':
            raise AttributeError(name)
        return lambda *args, **kwargs: self.calls.append((name, args)) or True


def _wait_for(predicate, seconds=20.0):
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        _APP.Yield(True)
        time.sleep(0.02)
    return predicate()


def setUpModule():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'polyglot', os.path.join(COMPONENT, 'init.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules['polyglot'] = module
    spec.loader.exec_module(module)
    global POLYGLOT
    POLYGLOT = module
    module.install_examples()


def tearDownModule():
    adapters.stop_all()
    shutil.rmtree(_APPDATA, ignore_errors=True)


def _user(*parts):
    from src.platform_utils import get_user_resource_path
    return get_user_resource_path(os.path.join('data', *parts))


def _needs(runtime_id):
    runtime = runtimes.by_id(runtime_id)
    if runtime is None or not runtime.available():
        raise unittest.SkipTest('%s is not on this machine' % runtime_id)


class EveryKindOfModuleIsCovered(unittest.TestCase):
    """Every add-on kind Titan has - the Component Manager's and the Action
    API's - can be written in another language. A kind added to Titan
    without a Polyglot binder fails here."""

    def test_the_component_managers_kinds(self):
        from src.titan_core import modules
        missing = [k for k in modules.KIND_IDS if k not in adapters.KINDS]
        self.assertEqual(missing, [])

    def test_the_action_apis_kinds(self):
        from src.titan_core.actions.kinds import ADDON_KINDS
        # A language is a catalogue of translations: data, not a program.
        code_kinds = [k for k, entry in ADDON_KINDS.items() if entry[3]]
        missing = [k for k in code_kinds if k not in adapters.KINDS]
        self.assertEqual(missing, [])

    def test_every_called_kind_has_an_entry_in_the_right_folder(self):
        from src.titan_core import modules
        for kind, (subdir, entry, manifest) in stubs.KINDS.items():
            self.assertIn(kind, adapters._BINDERS)
            self.assertEqual(subdir.replace(os.sep, '/'),
                             modules.subdir_of(kind), kind)

    def test_every_kind_has_an_example(self):
        examples = os.path.join(COMPONENT, 'examples')
        folders = {'app': 'applications', 'game': 'games',
                   'component': 'components', 'macro': 'macros',
                   'im_module': 'titanIM_modules', 'widget': 'applets',
                   'statusbar_applet': 'statusbar_applets',
                   'launcher': 'launchers',
                   'settings_interface': 'settings interfaces',
                   'shell_addon': 'shell addons',
                   'gamepad_mode': 'gamepad modes',
                   'tts_engine': 'titantts engines'}
        self.assertEqual(sorted(folders), sorted(adapters.KINDS))
        for kind, folder in folders.items():
            path = os.path.join(examples, folder)
            self.assertTrue(os.path.isdir(path) and os.listdir(path), kind)


class TheEntriesAreWritten(unittest.TestCase):
    def test_every_example_kind_has_its_python_entry(self):
        expected = {
            ('titanIM_modules', 'lua_echo', 'init.py'),
            ('applets', 'lua_counter', 'init.py'),
            ('applets', 'ruby_dice', 'init.py'),
            ('statusbar_applets', 'lua_uptime', 'main.py'),
            ('statusbar_applets', 'js_clock', 'main.py'),
            ('launchers', 'lua_launcher', 'init.py'),
            ('settings interfaces', 'lua_settings', 'init.py'),
            ('shell addons', 'lua_shell_addon', 'init.py'),
            (os.path.join('gamepad', 'modes'), 'lua_announcer', 'mode.py'),
            ('titantts engines', 'ruby_tones', '__engine__.py'),
        }
        for subdir, name, entry in expected:
            path = _user(subdir, name, entry)
            self.assertTrue(os.path.isfile(path), path)
            self.assertTrue(stubs.is_ours(path), path)

    def test_a_python_addon_is_never_touched(self):
        folder = os.path.join(ROOT, 'data', 'statusbar_applets', 'stopwatch')
        def read():
            with open(os.path.join(folder, 'main.py'), 'rb') as handle:
                return handle.read()
        before = read()
        self.assertEqual(stubs.ensure('statusbar_applet', folder), 'python')
        self.assertEqual(read(), before)

    def test_a_folder_that_is_not_an_addon_gets_nothing(self):
        folder = tempfile.mkdtemp(dir=_APPDATA)
        with open(os.path.join(folder, 'main.lua'), 'w') as handle:
            handle.write('-- not an add-on\n')
        self.assertEqual(stubs.ensure('tts_engine', folder), 'none')
        self.assertFalse(os.path.exists(os.path.join(folder, '__engine__.py')))

    def test_running_it_again_writes_nothing(self):
        self.assertEqual(stubs.ensure_all(), {})


class StatusbarApplets(unittest.TestCase):
    def _load(self, name):
        from src.titan_core.statusbar_applet_manager import StatusbarAppletManager
        manager = StatusbarAppletManager()
        self.assertIn(name, manager.applets, list(manager.applets))
        return manager.applets[name]['module']

    def test_lua(self):
        module = self._load('lua_uptime')
        self.assertTrue(module.get_statusbar_item_text().startswith('Session:'))
        self.assertEqual(module.get_statusbar_item_info()['update_interval'], 30)
        before = len(SPOKEN)
        module.on_statusbar_item_activate(None)
        self.assertTrue(_wait_for(lambda: len(SPOKEN) > before))
        self.assertIn('minutes', SPOKEN[-1])

    def test_javascript(self):
        _needs('javascript')
        module = self._load('js_clock')
        text = module.get_statusbar_item_text()
        self.assertTrue(text.startswith('JS '), text)


class Widgets(unittest.TestCase):
    def _widget(self, name):
        from src.ui.main_window_actions import _widget_modules
        for found, module, info in _widget_modules():
            if found == name:
                self.assertFalse(info.get('error'), info)
                return module, info
        self.fail('%s was not loaded' % name)

    def test_lua(self):
        module, info = self._widget('lua_counter')
        self.assertEqual(info['name'], 'Lua counter')
        widget = module.get_widget_instance(lambda *a, **k: None)
        self.assertEqual(widget.navigate('left'), (False, 0, 3))
        self.assertEqual(widget.navigate('right'), (True, 1, 3))
        self.assertEqual(widget.get_current_element(), 'Pears: 0')
        widget.activate_current_element()
        self.assertEqual(widget.get_current_element(), 'Pears: 1')

    def test_ruby(self):
        _needs('ruby')
        module, info = self._widget('ruby_dice')
        self.assertEqual(info['type'], 'button')
        widget = module.get_widget_instance(lambda *a, **k: None)
        self.assertEqual(widget.get_current_element(), 'Dice: Not thrown yet')
        widget.activate_current_element()
        self.assertIn(' in all', widget.get_current_element())


class TitanIM(unittest.TestCase):
    def test_lua_module_opens_and_talks_to_its_sounds(self):
        from src.network.im_module_manager import TitanIMModuleManager
        manager = TitanIMModuleManager()
        manager.load_modules()
        info = next(i for i in manager.modules if i['id'] == 'lua_echo')
        addon = info['module'].polyglot_addon
        sounds = Recorder()
        addon.objects['sounds'] = sounds
        self.assertEqual(manager.get_status_text('lua_echo'), '')
        ANSWERS[:] = ['hello', '']
        info['module'].open(None)
        self.assertTrue(_wait_for(lambda: ('goodbye', ()) in sounds.calls))
        self.assertIn('You wrote: hello', SPOKEN)
        self.assertEqual(manager.get_status_text('lua_echo'), '(1)')


class GamepadModes(unittest.TestCase):
    def test_lua_mode_is_a_real_gamepad_mode(self):
        from src.controller import gamepad_mode_api
        modes = gamepad_mode_api.load_custom_modes()
        mode = next(m for m in modes if m.mode_id == 'custom:lua_announcer')
        self.assertIsInstance(mode, gamepad_mode_api.GamepadMode)
        self.assertEqual(mode.get_display_name(), 'Button announcer (Lua)')
        self.assertTrue(mode.handle_button(3))
        self.assertIn('Button 3', SPOKEN)
        helpers = Recorder()
        mode_addon = type(mode).polyglot_addon
        mode_addon.objects['gamepad'] = helpers
        self.assertTrue(mode.handle_hat(1, 0))
        self.assertEqual(helpers.calls, [('tap', ('right',))])
        self.assertFalse(mode.handle_bumper(True))     # not defined: not used


class TtsEngines(unittest.TestCase):
    def test_ruby_engine_speaks_through_a_wav(self):
        _needs('ruby')
        from src.tts.engine_registry import EngineRegistry
        registry = EngineRegistry()
        engine = registry.get_engine('ruby_tones')
        self.assertIsNotNone(engine)
        self.assertTrue(engine.is_available())
        self.assertEqual([v['id'] for v in engine.get_voices()], ['high', 'low'])
        audio = engine.generate('ala ma kota', 0)
        self.assertIsNotNone(audio)
        self.assertGreater(len(audio), 500)          # milliseconds


class ShellAddons(unittest.TestCase):
    def test_lua_entry_is_offered_and_its_action_runs(self):
        from src.shell import addons
        manager = addons.ShellAddonManager()
        config = manager.config('lua_shell_addon')
        config.status = 0
        addon = manager.load('lua_shell_addon')
        self.assertIsNotNone(addon)
        self.assertIsNotNone(addon.hook('start_menu_items'))
        self.assertIsNone(addon.hook('taskbar_bands'))
        entries = manager.collect('start_menu', 'start_menu_items', None)
        entry = next(e for e in entries if e['id'] == 'lua_hello')
        self.assertEqual(entry['label'], 'Hello from Lua')
        entry['action']()
        self.assertTrue(_wait_for(
            lambda: 'Hello from a shell add-on in Lua' in SPOKEN))


class SettingsInterfaces(unittest.TestCase):
    def test_lua_interface_sets_and_saves(self):
        from src.settings import interfaces
        module = interfaces.manager().module('lua_settings')
        self.assertIsNotNone(module)
        api = Recorder()
        api.categories = lambda: [{'name': 'General', 'items': [
            {'id': 'general/x', 'label': 'X', 'value': 'old'}]}]
        # choose answers from 0, as Titan's dialog does: General, X, "new",
        # Save and close.
        ANSWERS[:] = [0, 0, 'new', 1]
        self.assertTrue(module.open_settings(api))
        self.assertTrue(_wait_for(lambda: ('save', ()) in api.calls))
        self.assertIn(('set', ('general/x', 'new')), api.calls)


def module_addon(module):
    return adapters.running()[next(k for k in adapters.running()
                                   if k[0] == 'launcher')]


class Launchers(unittest.TestCase):
    def test_lua_launcher_runs_and_ends_titan_when_it_ends(self):
        from src.titan_core.launcher_manager import LauncherManager
        manager = LauncherManager()
        config = manager.get_launcher_by_name('lua_launcher')
        self.assertIsNotNone(config)
        module = manager._load_module(manager._find_init_file(config.path),
                                      'lua_launcher')
        self.assertTrue(callable(getattr(module, 'start', None)))
        api = Recorder()
        api.get_applications = lambda: [{'name': 'Notes', 'shortname': 'tnotes'}]
        ANSWERS[:] = [0, 2]                   # Notes, then Exit (from 0)
        module.start(api)
        self.assertTrue(_wait_for(lambda: any(c[0] == 'request_exit'
                                              for c in api.calls)))
        names = [c[0] for c in api.calls]
        opened = [c for c in api.calls if c[0] == 'open_application']
        self.assertEqual(opened[0][1][0]['shortname'], 'tnotes')
        # Titan ends when the launcher does - after it has been used, not
        # the moment it starts (a refused wait ended it at once, live).
        self.assertLess(names.index('open_application'),
                        names.index('request_exit'))
        self.assertFalse(module_addon(module).error)

    def test_no_wait_is_longer_than_windows_allows(self):
        import inspect
        source = inspect.getsource(adapters)
        self.assertNotIn('10 ** 9', source)


class Macros(unittest.TestCase):
    def test_the_example_is_installed(self):
        folder = _user('macros', 'lua_greeting')
        self.assertTrue(os.path.isfile(os.path.join(folder, '__macro__.TCE')))

    def test_the_macro_managers_run_macro_is_taught_other_languages(self):
        import types
        from polyglotkit import hooks
        ran, launched = [], []
        fake = types.ModuleType('macros')
        fake.run_tcs = lambda *a, **k: None
        fake.run_macro = lambda info, parent=None: ran.append(info)
        previous = sys.modules.get('macros')
        sys.modules['macros'] = fake
        original_launch = hooks.launch
        hooks.launch = lambda *a: launched.append(a) or 1234
        try:
            hooks.install()
            self.assertTrue(getattr(fake.run_macro, 'polyglot', False))
            hooks.install()                      # twice is still once
            source = _user('macros', 'lua_greeting', 'main.lua')
            fake.run_macro({'script_path': source, 'type': '.lua'})
            self.assertEqual(launched[0][2], 'macro')
            self.assertEqual(launched[0][0], source)
            fake.run_macro({'script_path': 'x.tcs', 'type': '.tcs'})
            self.assertEqual(ran, [{'script_path': 'x.tcs', 'type': '.tcs'}])
        finally:
            hooks.launch = original_launch
            hooks._ORIGINALS.pop('macros', None)
            if previous is None:
                sys.modules.pop('macros', None)
            else:
                sys.modules['macros'] = previous

    def test_a_lua_macro_runs_its_main(self):
        from polyglotkit.guests import LuaGuest
        api = TitanAPI(_user('macros', 'lua_greeting'), 'Greeting',
                       kind='macro', titan_call=_titan_call)
        finished = threading.Event()
        ANSWERS[:] = ['Ala']
        guest = LuaGuest(api, _user('macros', 'lua_greeting', 'main.lua'),
                         lambda text: None,
                         lambda code, error: finished.set())
        guest.start()
        self.assertTrue(finished.wait(20))
        self.assertIn('Hello, Ala', SPOKEN)
        self.assertIn(('macros', 'list_macros', {}), ACTIONS)


class EverySdkServesTitansCalls(unittest.TestCase):
    """Titan.serve / titan.serve / Start-TitanServe in every SDK: the
    functions are announced, the arguments arrive as arguments, the answer
    comes back."""
    PROGRAMS = {
        'ruby': ('main.rb', "require 'titan'\n"
                 "Titan.serve('twice' => ->(x) { x * 2 },"
                 "            'add' => ->(a, b) { a + b })\n"),
        'javascript': ('main.js', "titan.serve({ twice: (x) => x * 2,"
                       " add: (a, b) => a + b });\n"),
        'powershell': ('main.ps1', '\ufeffImport-Module Titan\n'
                       'Start-TitanServe @{ twice = { param($x) $x * 2 };'
                       ' add = { param($a, $b) $a + $b } }\n'),
        'csharp': ('main.cs', 'using System; using System.Collections.Generic;\n'
                   'class P { static void Main() {\n'
                   ' var h = new Dictionary<string, Func<object[], object>>();\n'
                   ' h["twice"] = a => Convert.ToInt32(a[0]) * 2;\n'
                   ' h["add"] = a => Convert.ToInt32(a[0]) + Convert.ToInt32(a[1]);\n'
                   ' Titan.Serve(h); } }\n'),
    }

    def _check(self, runtime_id):
        _needs(runtime_id)
        name, text = self.PROGRAMS[runtime_id]
        folder = tempfile.mkdtemp(dir=_APPDATA)
        with open(os.path.join(folder, name), 'w', encoding='utf-8') as handle:
            handle.write(text)
        addon = adapters.ForeignAddon('statusbar_applet', folder,
                                      os.path.join(folder, name),
                                      runtimes.by_id(runtime_id))
        try:
            self.assertTrue(addon.start(), addon.error)
            self.assertTrue(addon.has('twice'), addon.error)
            self.assertFalse(addon.has('nothing_like_it'))
            self.assertEqual(addon.call('twice', 21, timeout=60), 42)
            self.assertEqual(addon.call('add', 2, 3, timeout=30), 5)
            self.assertEqual(addon.call('nothing_like_it', default='x'), 'x')
        finally:
            addon.stop()

    def test_ruby(self):
        self._check('ruby')

    def test_javascript(self):
        self._check('javascript')

    def test_powershell(self):
        self._check('powershell')

    def test_csharp(self):
        self._check('csharp')


class UsedWhereTitanUsesThem(unittest.TestCase):
    """check_addon with run: on Titan's real surfaces, not only loaded."""

    def test_the_shell_addons_entry_is_chosen_in_titans_start_menu(self):
        from src.titan_core import modules
        modules.set_enabled(modules.find('shell_addon', 'lua_shell_addon'), True)
        before = len(SPOKEN)
        answer = POLYGLOT.action_check_addon('lua_shell_addon', run=True)
        self.assertIn('Start menu: chose Hello from Lua', answer)
        self.assertTrue(_wait_for(lambda: 'Hello from a shell add-on in Lua'
                                  in SPOKEN[before:]))

    def test_the_gamepad_mode_is_handed_a_button_by_the_real_manager(self):
        from src.controller.controller_modes import get_mode_manager
        manager = get_mode_manager()
        before_mode = manager._mode_description(manager._current_cycle_entry())
        answer = POLYGLOT.action_check_addon('lua_announcer', run=True)
        self.assertIn('active: Button announcer (Lua)', answer)
        self.assertIn('button 0 used', answer)
        self.assertIn('Button 0', SPOKEN)
        self.assertEqual(
            manager._mode_description(manager._current_cycle_entry()),
            before_mode)


class TheComponentSaysWhatItRuns(unittest.TestCase):
    def test_addons_and_prepare(self):
        listing = POLYGLOT.action_addons()
        for name in ('lua_echo', 'lua_counter', 'lua_uptime', 'lua_launcher',
                     'lua_settings', 'lua_shell_addon', 'lua_announcer',
                     'ruby_tones'):
            self.assertIn(name, listing)
        self.assertIn('All of them were ready', POLYGLOT.prepare_addons())


if __name__ == '__main__':
    unittest.main(verbosity=2)
