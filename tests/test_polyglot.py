# -*- coding: utf-8 -*-
"""Polyglot: Titan applications, games and components in other languages.

Run it directly: ``python tests/test_polyglot.py``. Nothing here shows a
window, speaks, plays a sound or reaches Titan: Titan's half is a recorder,
dialogs are built for real and answered in code, and APPDATA is a temporary
folder so the user's own languages file and examples are never touched. The
languages whose interpreter is missing on this machine are skipped by name.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPONENT = os.path.join(ROOT, 'data', 'components', 'polyglot')
EXAMPLES = os.path.join(COMPONENT, 'examples')
_APPDATA = tempfile.mkdtemp(prefix='polyglot_test_')
os.environ['APPDATA'] = _APPDATA
os.environ['TITAN_LANGUAGE'] = 'en'
sys.path[:0] = [COMPONENT, ROOT]

from polyglotkit import runtimes, guests, hooks, components   # noqa: E402
from polyglotkit.api import TitanAPI, ApiError                   # noqa: E402


class _Result(object):
    def __init__(self, text='done', ok=True):
        self.text, self.ok = text, ok


class ScriptedAPI(TitanAPI):
    """The real API, with Titan replaced by a recorder and the dialogs by
    answers given in advance."""

    def __init__(self, folder, answers=(), kind='app', titan=True):
        self.calls = []

        def titan_call(addon, action, **args):
            self.calls.append((addon, action, args))
            return _Result('done %s.%s' % (addon, action))
        TitanAPI.__init__(self, folder, 'probe', kind=kind,
                          titan_call=titan_call if titan else None,
                          log=lambda text: self.calls.append(('log', text)))
        self.answers = list(answers)

    def _answer(self, kind, *details):
        self.calls.append((kind,) + details)
        return self.answers.pop(0) if self.answers else None

    def message(self, text, title=None):
        self.calls.append(('message', text))
        return True

    def text(self, text, title=None):
        self.calls.append(('text', text))
        return True

    def ask(self, prompt, default='', title=None, multiline=False,
            password=False):
        return self._answer('ask', prompt)

    def choose(self, prompt, options, title=None, selected=0):
        return self._answer('choose', prompt, list(options), selected)

    def confirm(self, text, title=None):
        return self._answer('confirm', text)

    def open_window(self, title=None):
        self.calls.append(('open_window', title))
        return True

    def spoken(self):
        return [c[2]['text'] for c in self.calls
                if c[:2] == ('titan', 'speak')]


def run_guest(path, api, timeout=120):
    runtime = runtimes.for_file(path)
    done = threading.Event()
    outcome = {}

    def on_exit(code, error):
        outcome.update(code=code, error=error)
        done.set()
    guest = guests.make_guest(runtime, api, path, lambda text: None, on_exit)
    guest.start()
    if not done.wait(timeout):
        raise AssertionError('%s did not finish' % path)
    return outcome


def _write(folder, name, text, encoding='utf-8'):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, 'w', encoding=encoding) as handle:
        handle.write(text)
    return path


class TheLanguagesAreData(unittest.TestCase):
    def setUp(self):
        self.addCleanup(lambda: os.path.exists(runtimes.user_table_path())
                        and os.remove(runtimes.user_table_path()))

    def test_a_file_is_known_by_its_extension(self):
        self.assertEqual(runtimes.for_file('x/main.lua').id, 'lua')
        self.assertEqual(runtimes.for_file('x/main.RB').id, 'ruby')
        self.assertEqual(runtimes.for_file('x/main.cs').id, 'csharp')
        self.assertEqual(runtimes.for_file('x/main.js').id, 'javascript')

    def test_titans_own_kinds_are_never_taken(self):
        for name in ('a.py', 'a.pyc', 'a.pyd', 'a.exe', 'noext'):
            self.assertIsNone(runtimes.for_file(name), name)

    def test_lua_needs_nothing_installed(self):
        lua = runtimes.by_id('lua')
        self.assertTrue(lua.inprocess)
        self.assertTrue(lua.available())
        self.assertEqual(lua.why_not(), '')

    def test_a_missing_interpreter_is_said_in_a_sentence(self):
        runtime = runtimes.Runtime('nothing', 'Nothing', ['.zz'],
                                   command=['{exe}', '{file}'],
                                   find=['no-such-interpreter-anywhere'])
        self.assertFalse(runtime.available())
        self.assertIn('no-such-interpreter-anywhere', runtime.why_not())
        self.assertIn('Polyglot', runtime.why_not())

    def test_the_users_table_adds_a_language_and_moves_an_interpreter(self):
        os.makedirs(os.path.dirname(runtimes.user_table_path()), exist_ok=True)
        with open(runtimes.user_table_path(), 'w', encoding='utf-8') as handle:
            json.dump({'runtimes': [
                {'id': 'mylang', 'name': 'My language',
                 'extensions': ['.my'], 'command': ['{exe}', '{file}'],
                 'find': [sys.executable]},
                {'id': 'ruby', 'find': [sys.executable]}]}, handle)
        mine = runtimes.for_file('a.my')
        self.assertEqual(mine.id, 'mylang')
        self.assertEqual(mine.source, 'user')
        self.assertEqual(mine.executable(), sys.executable)
        ruby = runtimes.by_id('ruby')
        self.assertEqual(ruby.executable(), sys.executable)
        # Only `find` was named: the rest is the built-in Ruby's.
        self.assertEqual(ruby.extensions, ['.rb'])
        self.assertEqual(ruby.command, ['{exe}', '{file}'])

    def test_a_broken_users_table_leaves_the_built_in_languages(self):
        os.makedirs(os.path.dirname(runtimes.user_table_path()), exist_ok=True)
        with open(runtimes.user_table_path(), 'w', encoding='utf-8') as handle:
            handle.write('{ not json')
        self.assertEqual(runtimes.for_file('a.lua').id, 'lua')

    def test_the_sdk_is_on_the_guests_paths(self):
        env = runtimes.by_id('ruby').environment('x/main.rb')
        self.assertTrue(env['RUBYLIB'].startswith(runtimes.SDK_DIR))
        self.assertTrue(env['NODE_PATH'].startswith(runtimes.SDK_DIR))
        self.assertEqual(env['TITAN_POLYGLOT'], '1')
        self.assertNotIn('RUBYOPT', env)

    def test_a_powershell_module_is_where_import_module_looks(self):
        self.assertTrue(os.path.isfile(os.path.join(
            runtimes.SDK_DIR, 'Titan', 'Titan.psm1')))


class ACompilerIsAskedOnceAndRemembered(unittest.TestCase):
    """A compiled language: compile into a cache, run what came out, and do
    not compile again until the source changes."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(dir=_APPDATA)
        self.source = _write(self.folder, 'prog.fake', 'print("hi")')
        self.compiler = _write(self.folder, 'compiler.py', (
            "import sys, shutil\n"
            "open(sys.argv[2] + '.count', 'a').write('x')\n"
            "shutil.copy(sys.argv[1], sys.argv[2])\n"))
        self.runtime = runtimes.Runtime(
            'fake', 'Fake', ['.fake'],
            compile=['{exe}', self.compiler, '{file}', '{out}'],
            command=['{exe}', '{out}'], output='{name}.py',
            find=[sys.executable])

    def test_compiled_then_cached_then_compiled_again(self):
        command = self.runtime.prepare(self.source)
        out = command[-1]
        self.assertTrue(os.path.isfile(out))
        self.runtime.prepare(self.source)
        with open(out + '.count') as handle:
            self.assertEqual(handle.read(), 'x')
        future = time.time() + 5
        os.utime(self.source, (future, future))
        self.runtime.prepare(self.source)
        with open(out + '.count') as handle:
            self.assertEqual(handle.read(), 'xx')

    def test_a_failed_compile_says_what_the_compiler_said(self):
        bad = runtimes.Runtime('bad', 'Bad', ['.bad'],
                               compile=['{exe}', '-c', 'import sys; '
                                        'sys.stderr.write("line 3: oops"); '
                                        'sys.exit(1)'],
                               find=[sys.executable])
        with self.assertRaises(RuntimeError) as caught:
            bad.prepare(self.source)
        self.assertIn('line 3: oops', str(caught.exception))


class TheManagersAreReachedFromOutside(unittest.TestCase):
    """The two names both of Titan's managers look up at launch time."""

    def setUp(self):
        self.launched = []
        self.fake = types.ModuleType('fake_manager')
        self.fake.find_executable_file = lambda base, openfile: (
            (os.path.join(base, openfile), 'py')
            if openfile.endswith('.py') else (None, None))
        self.fake._run_executable = lambda f, cwd, *a, **k: ('original', f)
        sys.modules['fake_manager'] = self.fake
        self.saved = hooks._MODULES, dict(hooks._ORIGINALS)
        hooks._MODULES = (('fake_manager', 'app'),)
        hooks._ORIGINALS.clear()
        self.saved_launch = hooks.launch
        hooks.launch = lambda *a: self.launched.append(a) or 4242
        self.folder = tempfile.mkdtemp(dir=_APPDATA)
        _write(self.folder, 'main.lua', 'titan.log("x")')

    def tearDown(self):
        hooks.uninstall()
        hooks._MODULES = self.saved[0]
        hooks._ORIGINALS.update(self.saved[1])
        hooks.launch = self.saved_launch
        sys.modules.pop('fake_manager', None)

    def test_a_source_in_another_language_is_an_executable(self):
        hooks.install()
        found = self.fake.find_executable_file(self.folder, 'main.lua')
        self.assertEqual(found, (os.path.join(self.folder, 'main.lua'), 'exe'))
        self.assertEqual(self.fake.find_executable_file(self.folder, 'main'),
                         found)
        pid = self.fake._run_executable(found[0], self.folder, console=False)
        self.assertEqual(pid, 4242)
        self.assertEqual(self.launched[0][2], 'app')
        self.assertEqual(self.launched[0][3].id, 'lua')

    def test_everything_else_is_titans_own(self):
        hooks.install()
        self.assertEqual(self.fake.find_executable_file(self.folder, 'a.py'),
                         (os.path.join(self.folder, 'a.py'), 'py'))
        self.assertEqual(self.fake._run_executable('x.exe', self.folder),
                         ('original', 'x.exe'))
        self.assertEqual(self.launched, [])

    def test_installing_twice_does_not_wrap_twice_and_uninstall_restores(self):
        original = self.fake._run_executable
        hooks.install()
        hooks.install()
        self.assertEqual(self.fake._run_executable('x.exe', '.'),
                         ('original', 'x.exe'))
        hooks.uninstall()
        self.assertIs(self.fake._run_executable, original)

    def test_the_real_managers_are_reachable_by_those_names(self):
        # The whole approach rests on this; a rename in Titan must fail here.
        for name in ('app_manager', 'game_manager'):
            path = os.path.join(ROOT, 'src', 'titan_core', name + '.py')
            with open(path, encoding='utf-8') as handle:
                source = handle.read()
            self.assertIn('def find_executable_file(', source)
            self.assertIn('def _run_executable(', source)
            self.assertIn('exec_file, file_type = find_executable_file(',
                          source)
            self.assertIn("if file_type == 'exe'", source)
        with open(os.path.join(ROOT, 'src', 'titan_core', 'app_manager.py'),
                  encoding='utf-8') as handle:
            source = handle.read()
        for name in ('def get_python_executable(', 'SITEPACKAGES_DIR',
                     'resource_path'):
            self.assertIn(name, source)

    def test_the_host_command_is_titans_own_python(self):
        command, root = hooks.host_command(
            os.path.join(self.folder, 'main.lua'), self.folder, 'game',
            runtimes.by_id('lua'), 'T', 'id')
        self.assertEqual(command[1], '-c')
        self.assertIn('polyglotkit.host', command[2])
        self.assertIn("'--kind', 'game'", command[2])
        compile(command[2], 'bootstrap', 'exec')


class LuaPrograms(unittest.TestCase):
    def test_the_example_application_runs_end_to_end(self):
        path = os.path.join(EXAMPLES, 'applications', 'lua_hello', 'main.lua')
        api = ScriptedAPI(os.path.dirname(path),
                          ['Anna', 0, 1, 2, 3, 'note text', 4, 5])
        outcome = run_guest(path, api)
        self.assertEqual(outcome['code'], 0, outcome)
        spoken = api.spoken()
        self.assertEqual(spoken[0], 'Hello, Anna!')
        self.assertIn('Hello from Lua, Anna', spoken)
        self.assertTrue(any(t.startswith('You rolled ') for t in spoken))
        self.assertIn(('tnotes', 'create_note',
                       {'title': 'From Lua', 'text': 'note text'}), api.calls)
        self.assertEqual(spoken[-1], 'Goodbye, Anna')
        # Lua counts from 1, the dialog from 0: the cursor comes back on the
        # option chosen last.
        chooses = [c for c in api.calls if c[0] == 'choose']
        self.assertEqual([c[3] for c in chooses], [0, 0, 1, 2, 3, 4])

    def test_the_example_game_reads_keys_and_places_its_speech(self):
        path = os.path.join(EXAMPLES, 'games', 'lua_catch', 'game.lua')
        api = ScriptedAPI(os.path.dirname(path), kind='game')
        for key in ('left', 'left', 'escape'):
            api.post({'type': 'key', 'key': key, 'down': True})
        outcome = run_guest(path, api)
        self.assertEqual(outcome['code'], 0, outcome)
        self.assertIn(('open_window', 'Catch the balls'), api.calls)
        placed = [c[2] for c in api.calls if c[:2] == ('titan', 'speak')
                  and 'position' in c[2]]
        self.assertEqual([(p['text'], p['position']) for p in placed[:2]],
                         [('2', -0.5), ('1', -1)])
        self.assertTrue(api.spoken()[-1].startswith('Game over'))

    def test_a_theme_sound_is_found_and_played_through_titan(self):
        folder = tempfile.mkdtemp(dir=_APPDATA)
        path = _write(folder, 'main.lua',
                      'assert(titan.play("core/SELECT.ogg", -1))\n'
                      'assert(not titan.play("no/such/sound.ogg"))\n')
        api = ScriptedAPI(folder)
        api.play = TitanAPI.play.__get__(api)
        outcome = run_guest(path, api)
        # The second call is refused (there is no such sound) as a Lua error.
        self.assertEqual(outcome['code'], 1)
        played = [c[2] for c in api.calls if c[:2] == ('titan', 'play_sound')]
        self.assertEqual(len(played), 1)
        self.assertTrue(played[0]['path'].lower().endswith(
            os.path.join('core', 'select.ogg')))
        self.assertEqual(played[0]['position'], -1.0)

    def test_a_refusal_is_a_lua_error_pcall_catches(self):
        folder = tempfile.mkdtemp(dir=_APPDATA)
        path = _write(folder, 'main.lua', (
            'local ok, err = pcall(function() return titan.choose("x", {}) end)\n'
            'titan.log("pcall " .. tostring(ok) .. " " .. tostring(err))\n'))
        api = ScriptedAPI(folder)
        api.choose = TitanAPI.choose.__get__(api)
        outcome = run_guest(path, api)
        self.assertEqual(outcome['code'], 0, outcome)
        self.assertIn(('log', 'pcall false Nothing to choose from.'), api.calls)

    def test_an_action_without_titan_answers_rather_than_ending_the_program(self):
        folder = tempfile.mkdtemp(dir=_APPDATA)
        path = _write(folder, 'main.lua', (
            'local ok, text = titan.action("tnotes", "list_notes", {})\n'
            'titan.log(tostring(ok) .. "|" .. text)\n'))
        api = ScriptedAPI(folder, titan=False)
        outcome = run_guest(path, api)
        self.assertEqual(outcome['code'], 0, outcome)
        self.assertIn(('log', 'false|Titan is not running.'), api.calls)

    def test_a_lua_error_ends_the_program_with_its_place(self):
        folder = tempfile.mkdtemp(dir=_APPDATA)
        path = _write(folder, 'main.lua', 'local x = nil\nx.y = 1\n')
        outcome = run_guest(path, ScriptedAPI(folder))
        self.assertEqual(outcome['code'], 1)
        self.assertIn('main.lua', outcome['error'])

    def test_a_game_loop_that_waits_is_never_stopped_by_the_step_ceiling(self):
        folder = tempfile.mkdtemp(dir=_APPDATA)
        path = _write(folder, 'main.lua', (
            'for frame = 1, 3 do\n'
            '  for i = 1, 1000 do local y = i * 2 end\n'
            '  titan.next_event(0)\n'
            'end\n'
            'titan.log("done")\n'))
        api = ScriptedAPI(folder)
        guest_runtime = []
        original = guests.LuaGuest.__init__

        def spy(self, *a, **k):
            original(self, *a, **k)
            self.interpreter.MAX_STEPS = 2500
            guest_runtime.append(self)
        guests.LuaGuest.__init__ = spy
        try:
            outcome = run_guest(path, api)
        finally:
            guests.LuaGuest.__init__ = original
        self.assertEqual(outcome['code'], 0, outcome)
        self.assertIn(('log', 'done'), api.calls)


class TheLineProtocol(unittest.TestCase):
    """A guest in any language: one JSON object per line, answered in kind.
    Python plays the guest here, so this runs on every machine."""

    def _guest(self, source):
        folder = tempfile.mkdtemp(dir=_APPDATA)
        path = _write(folder, 'guest.py', source)
        return folder, path

    def _run(self, source, answers=()):
        folder, path = self._guest(source)
        api = ScriptedAPI(folder, answers)
        done = threading.Event()
        outcome = {}
        guest = guests.ProcessGuest(
            api, path, lambda text: api.calls.append(('guestlog', text)),
            lambda code, error: (outcome.update(code=code, error=error),
                                 done.set()),
            [sys.executable, path])
        guest.start()
        self.assertTrue(done.wait(60))
        return api, outcome

    CLIENT = (
        "import json, sys\n"
        "n = 0\n"
        "def call(name, *args, **named):\n"
        "    global n\n"
        "    n += 1\n"
        "    sys.stdout.write(json.dumps({'id': n, 'call': name,\n"
        "        'args': named or list(args)}) + '\\n')\n"
        "    sys.stdout.flush()\n"
        "    reply = json.loads(sys.stdin.readline())\n"
        "    assert reply['id'] == n\n"
        "    if not reply['ok']: raise RuntimeError(reply['error'])\n"
        "    return reply['value']\n")

    def test_calls_are_answered_in_order_with_named_and_positional_args(self):
        api, outcome = self._run(self.CLIENT + (
            "name = call('ask', 'Name?')\n"
            "call('speak', text='Hi ' + name, interrupt=False)\n"
            "i = call('choose', 'Pick', ['a', 'b'])\n"
            "call('log', 'chose %s' % i)\n"), ['Zoë', 1])
        self.assertEqual(outcome['code'], 0, outcome)
        self.assertEqual(api.spoken(), ['Hi Zoë'])
        self.assertIn(('log', 'chose 1'), api.calls)

    def test_a_stray_print_goes_to_the_log_not_the_wire(self):
        api, outcome = self._run(self.CLIENT + (
            "print('hello there')\n"
            "print('{not json')\n"
            "call('speak', 'still fine')\n"))
        self.assertEqual(outcome['code'], 0, outcome)
        self.assertEqual(api.spoken(), ['still fine'])
        self.assertIn(('guestlog', 'output: hello there'), api.calls)

    def test_an_unknown_call_is_refused_by_name(self):
        api, outcome = self._run(self.CLIENT + (
            "try:\n"
            "    call('format_disk')\n"
            "except RuntimeError as e:\n"
            "    call('log', str(e))\n"))
        self.assertIn(('log', "There is no call named 'format_disk'."),
                      api.calls)

    def test_a_call_without_an_id_is_not_answered(self):
        api, outcome = self._run(
            "import json, sys\n"
            "sys.stdout.write(json.dumps({'call': 'log', 'args': ['quiet']})"
            " + '\\n')\n"
            "sys.stdout.flush()\n")
        self.assertIn(('log', 'quiet'), api.calls)

    def test_a_program_that_fails_is_reported_with_what_it_wrote(self):
        api, outcome = self._run("import sys\nsys.stderr.write('boom here')\n"
                                 "sys.exit(3)\n")
        self.assertEqual(outcome['code'], 3)
        self.assertIn('boom here', outcome['error'])


def _ruby():
    runtime = runtimes.by_id('ruby')
    return runtime if runtime and runtime.available() else None


class OtherLanguagesForReal(unittest.TestCase):
    """The examples, on the interpreters this machine really has."""

    @unittest.skipUnless(_ruby(), 'no Ruby on this machine')
    def test_ruby(self):
        if sys.platform == 'win32':
            self.assertTrue(_ruby().executable().startswith(
                runtimes.INTERPRETERS))
        path = os.path.join(EXAMPLES, 'applications', 'ruby_hello', 'main.rb')
        api = ScriptedAPI(os.path.dirname(path), ['Ola', 1])
        outcome = run_guest(path, api)
        self.assertEqual(outcome['code'], 0, outcome)
        self.assertEqual(api.spoken(), ['Hello from Ruby, Ola'])
        self.assertIn(('message', 'You picked: Pear'), api.calls)

    @unittest.skipUnless(sys.platform == 'win32' and
                         runtimes.by_id('powershell') and
                         runtimes.by_id('powershell').available(),
                         'no PowerShell')
    def test_powershell_with_polish_letters(self):
        os.environ['TITAN_LANGUAGE'] = 'pl'
        try:
            path = os.path.join(EXAMPLES, 'applications', 'powershell_hello',
                                'main.ps1')
            api = ScriptedAPI(os.path.dirname(path), ['Łucja'])
            outcome = run_guest(path, api)
        finally:
            os.environ['TITAN_LANGUAGE'] = 'en'
        self.assertEqual(outcome['code'], 0, outcome)
        self.assertIn(('ask', 'Jak masz na imię?'), api.calls)
        self.assertTrue(api.spoken()[0].startswith('Cześć z PowerShella, Łucja'))

    def test_javascript_on_the_carried_quickjs(self):
        runtime = runtimes.by_id('javascript')
        if not runtime.available():
            self.skipTest('no QuickJS for this platform')
        self.assertTrue(runtime.executable().startswith(runtimes.INTERPRETERS))
        os.environ['TITAN_LANGUAGE'] = 'pl'
        try:
            path = os.path.join(EXAMPLES, 'applications', 'javascript_hello',
                                'main.js')
            api = ScriptedAPI(os.path.dirname(path), ['Łucja'])
            outcome = run_guest(path, api)
        finally:
            os.environ['TITAN_LANGUAGE'] = 'en'
        self.assertEqual(outcome['code'], 0, outcome)
        self.assertEqual(api.spoken(), [
            'Cześć z JavaScriptu, Łucja. Twoje imię ma 5 znaków.'])

    @unittest.skipUnless(sys.platform == 'win32', 'csc.exe is Windows')
    def test_csharp_compiled_by_windows_own_compiler(self):
        runtime = runtimes.by_id('csharp')
        self.assertTrue(runtime.available(), runtime.why_not())
        path = os.path.join(EXAMPLES, 'applications', 'csharp_hello', 'main.cs')
        api = ScriptedAPI(os.path.dirname(path), ['Jan'])
        api.wait = lambda seconds: True
        outcome = run_guest(path, api, timeout=300)
        self.assertEqual(outcome['code'], 0, outcome)
        self.assertTrue(api.spoken()[0].startswith('Hello from C#, Jan'))


class NothingHasToBeInstalled(unittest.TestCase):
    """On a machine with nothing but Windows: Lua, JavaScript, Ruby, C# and
    PowerShell must all be found - inside this component or inside Windows
    itself - and never on a PATH somebody else's machine may not have."""

    @unittest.skipUnless(sys.platform == 'win32', 'Windows')
    def test_every_carried_language_is_found_with_only_windows_on_path(self):
        windows = os.environ.get('WINDIR', r'C:\Windows')
        saved = os.environ['PATH']
        os.environ['PATH'] = os.pathsep.join([
            os.path.join(windows, 'System32'), windows,
            os.path.join(windows, 'System32', 'WindowsPowerShell', 'v1.0')])
        try:
            for language in ('lua', 'javascript', 'ruby', 'csharp',
                             'powershell'):
                runtime = runtimes.by_id(language)
                self.assertTrue(runtime.available(), language)
                if runtime.inprocess:
                    continue
                where = os.path.normcase(runtime.executable())
                self.assertTrue(
                    where.startswith(os.path.normcase(runtimes.INTERPRETERS))
                    or where.startswith(os.path.normcase(windows)),
                    (language, where))
        finally:
            os.environ['PATH'] = saved

    def test_the_carried_interpreters_bring_their_licences(self):
        for name in ('ruby', 'quickjs'):
            folder = os.path.join(runtimes.INTERPRETERS, name)
            self.assertTrue(any(f.upper().startswith('LICENSE')
                                for f in os.listdir(folder)), name)


class ComponentsInOtherLanguages(unittest.TestCase):
    class Manager(object):
        def __init__(self):
            self.menus = {}

        def register_menu_function(self, name, function):
            self.menus[name] = function

    def setUp(self):
        self.said = []
        self.saved = components.titan_call
        components.titan_call = lambda addon, action, **a: (
            self.said.append((addon, action, a)) or _Result())
        import polyglotkit.components as module
        self.module = module
        self.saved_gui = module.gui_caller
        module.gui_caller = lambda: (lambda function: function())

    def tearDown(self):
        components.stop_all()
        components.titan_call = self.saved
        self.module.gui_caller = self.saved_gui

    def test_a_python_component_is_never_taken(self):
        folder = tempfile.mkdtemp(dir=_APPDATA)
        _write(folder, 'init.py', '')
        _write(folder, 'init.lua', '')
        self.assertEqual(components.init_file(folder), (None, None))

    def test_the_lua_example_component_adds_a_working_menu_entry(self):
        folder = os.path.join(EXAMPLES, 'components', 'lua_clock')
        path, runtime = components.init_file(folder)
        self.assertEqual(runtime.id, 'lua')
        manager = self.Manager()
        component = components.ForeignComponent(folder, path, runtime, manager)
        components._running['lua_clock'] = component
        self.assertTrue(component.start(), component.error)
        self.assertEqual(list(manager.menus), ['Lua clock: say the time'])
        manager.menus['Lua clock: say the time'](None)
        component.worker.submit(lambda: None, wait=5)
        self.assertTrue(self.said and self.said[0][2]['text'].startswith(
            'It is '))

    def test_a_declared_menu_entry_reaches_a_process_component(self):
        folder = tempfile.mkdtemp(dir=_APPDATA)
        _write(folder, '__component__.TCE',
               '[component]\nname = P\nstatus = 0\nmenu = One; Two\n')
        _write(folder, 'init.fake', '')
        runtime = runtimes.Runtime('fake', 'Fake', ['.fake'], command=[
            sys.executable, '-c',
            "import json,sys\n"
            "sys.stdout.write(json.dumps({'id':1,'call':'next_event',"
            "'args':[10]})+'\\n'); sys.stdout.flush()\n"
            "e=json.loads(sys.stdin.readline())['value']\n"
            "sys.stdout.write(json.dumps({'id':2,'call':'speak',"
            "'args':['got '+e['label']]})+'\\n'); sys.stdout.flush()\n"
            "sys.stdin.readline()\n"], find=[])
        manager = self.Manager()
        component = components.ForeignComponent(
            folder, os.path.join(folder, 'init.fake'), runtime, manager)
        components._running['p'] = component
        self.assertTrue(component.start(), component.error)
        self.assertEqual(list(manager.menus), ['One', 'Two'])
        manager.menus['Two'](None)
        component.guest.thread.join(30)
        self.assertEqual(self.said[0][2]['text'], 'got Two')


class RealWidgets(unittest.TestCase):
    """The dialogs and the game window, built for real and never shown."""

    @classmethod
    def setUpClass(cls):
        import wx
        cls.wx = wx
        cls.app = wx.App(False)

    def _api(self):
        return TitanAPI(_APPDATA, 'Probe', titan_call=lambda *a, **k:
                        _Result(), log=lambda t: None)

    def _modal(self, answer, setup=None):
        wx = self.wx
        seen = {}

        def show(dialog):
            seen['dialog'] = dialog
            if setup:
                setup(dialog)
            return answer
        saved = {cls: cls.ShowModal for cls in (
            wx.Dialog, wx.TextEntryDialog, wx.SingleChoiceDialog,
            wx.MessageDialog)}
        for cls in saved:
            cls.ShowModal = show
        self.addCleanup(lambda: [setattr(cls, 'ShowModal', f)
                                 for cls, f in saved.items()])
        return seen

    def test_ask_answers_the_text_or_none(self):
        wx = self.wx
        self._modal(wx.ID_OK, lambda d: d.SetValue('typed'))
        self.assertEqual(self._api().ask('Name?', 'x'), 'typed')
        self._modal(wx.ID_CANCEL)
        self.assertIsNone(self._api().ask('Name?'))

    def test_choose_answers_the_index_from_zero(self):
        wx = self.wx
        self._modal(wx.ID_OK, lambda d: d.SetSelection(2))
        self.assertEqual(self._api().choose('Pick', ['a', 'b', 'c']), 2)

    def test_confirm_text_and_message(self):
        wx = self.wx
        self._modal(wx.ID_YES)
        self.assertTrue(self._api().confirm('Sure?'))
        seen = self._modal(wx.ID_CANCEL)
        self.assertTrue(self._api().text('Long text', 'Read me'))
        self.assertEqual(seen['dialog'].GetTitle(), 'Read me')
        self.assertTrue(self._api().message('Hi'))

    def test_the_game_window_reports_keys_and_lets_go_on_leaving(self):
        wx = self.wx
        saved = wx.Frame.Show, wx.Frame.Raise
        wx.Frame.Show = lambda self, *a: True
        wx.Frame.Raise = lambda self: None
        try:
            api = self._api()
            api.open_window('My game')
            window = api.window
            self.assertEqual(window.panel.GetName(), 'My game')

            class Key(object):
                def __init__(self, code):
                    self.code = code

                def GetKeyCode(self):
                    return self.code

                def ShiftDown(self):
                    return False

                def ControlDown(self):
                    return True

                def AltDown(self):
                    return False

                def Skip(self):
                    pass
            while api.next_event(0) is not None:    # the window's own focus
                pass
            window._down(Key(wx.WXK_LEFT))
            window._down(Key(wx.WXK_LEFT))
            window._down(Key(ord('A')))
            first = api.next_event(0)
            self.assertEqual((first['key'], first['down'], first['repeat'],
                              first['ctrl']), ('left', True, False, True))
            self.assertTrue(api.next_event(0)['repeat'])
            self.assertEqual(api.next_event(0)['key'], 'a')

            class Leave(object):
                def GetActive(self):
                    return False

                def Skip(self):
                    pass
            window._activate(Leave())
            released = []
            while True:
                event = api.next_event(0)
                if event is None:
                    break
                released.append(event)
            self.assertEqual(sorted(e['key'] for e in released
                                    if e['type'] == 'key'), ['a', 'left'])
            self.assertEqual(released[-1], {'type': 'focus', 'active': False})
            api.close_window()
        finally:
            wx.Frame.Show, wx.Frame.Raise = saved


class TheComponentItself(unittest.TestCase):
    def test_actions_are_declared_with_names(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'polyglot_component_under_test',
            os.path.join(COMPONENT, 'init.py'))
        module = importlib.util.module_from_spec(spec)
        saved = hooks.install
        hooks.install = lambda: []
        try:
            spec.loader.exec_module(module)
        finally:
            hooks.install = saved
        names = [a['name'] for a in module.TITAN_ACTIONS]
        self.assertEqual(names, ['list_languages', 'run_file',
                                 'install_examples', 'prepare_addons',
                             'addons', 'check_addon', 'components'])
        self.assertIn('Lua', module.action_list_languages())
        self.assertIn('There is no file',
                      module.action_run_file(os.path.join(_APPDATA, 'none.lua')))

        target = os.path.join(_APPDATA, 'titosoft', 'Titan', 'data')
        module._user_data = lambda kind: os.path.join(target, kind)
        text = module.install_examples()
        self.assertIn('lua_hello', text)
        self.assertTrue(os.path.isfile(os.path.join(
            target, 'games', 'lua_catch', 'game.lua')))
        self.assertTrue(os.path.isfile(os.path.join(
            target, 'components', 'lua_clock', 'init.lua')))
        self.assertIn('Already there', module.install_examples())

    def test_every_example_names_a_file_a_language_answers(self):
        for kind in ('applications', 'games'):
            for name in os.listdir(os.path.join(EXAMPLES, kind)):
                folder = os.path.join(EXAMPLES, kind, name)
                manifest = [f for f in os.listdir(folder)
                            if f.lower() in ('__app.tce', '__game.tce')][0]
                with open(os.path.join(folder, manifest),
                          encoding='utf-8') as handle:
                    values = dict(line.strip().split('=', 1)
                                  for line in handle if '=' in line)
                openfile = values['openfile'].strip('"')
                path, runtime = hooks.resolve(folder, openfile)
                self.assertTrue(path and runtime, (kind, name, openfile))

    def test_the_polish_catalogue_has_every_string(self):
        import ast
        import gettext
        ids = set()
        for root, _dirs, files in os.walk(COMPONENT):
            if 'lua' in root.split(os.sep) or 'examples' in root:
                continue
            for name in files:
                if name.endswith('.py'):
                    with open(os.path.join(root, name), encoding='utf-8') as h:
                        tree = ast.parse(h.read())
                    for node in ast.walk(tree):
                        if (isinstance(node, ast.Call) and
                                getattr(node.func, 'id', None) == '_' and
                                node.args and
                                isinstance(node.args[0], ast.Constant)):
                            ids.add(node.args[0].value)
        catalogue = gettext.translation(
            'polyglot', os.path.join(COMPONENT, 'languages'), ['pl'])
        missing = [i for i in ids if catalogue.gettext(i) == i
                   and i not in ('Interpreter',)]
        self.assertEqual(missing, [])

    def test_the_powershell_example_carries_a_bom(self):
        with open(os.path.join(EXAMPLES, 'applications', 'powershell_hello',
                               'main.ps1'), 'rb') as handle:
            self.assertEqual(handle.read(3), b'\xef\xbb\xbf')


class LanguagesAreAddedInTheSettings(unittest.TestCase):
    """Settings -> Polyglot: the user's table, edited through the page."""

    def setUp(self):
        from polyglotkit import settings_page
        self.page = settings_page
        if os.path.isfile(runtimes.user_table_path()):
            os.remove(runtimes.user_table_path())

    tearDown = setUp

    def test_a_command_is_one_line_and_a_list_of_arguments(self):
        parts = ['{exe}', r'C:\Program Files\x\run.js', '--flag', '{file}']
        line = self.page.join_command(parts)
        self.assertEqual(line, r'{exe} "C:\Program Files\x\run.js" --flag {file}')
        self.assertEqual(self.page.split_command(line), parts)
        self.assertEqual(self.page.split_command(''), [])
        self.assertEqual(self.page.split_extensions('kt, .KTS .kt'),
                         ['.kt', '.kts'])
        self.assertEqual(self.page.split_env('A=1\nbroken\nB = x=y'),
                         ({'A': '1', 'B': 'x=y'}, ['broken']))

    def test_a_language_added_is_run_and_wins_its_extension(self):
        languages = self.page.Languages()
        entry = {'id': 'mynode', 'name': 'My Node', 'extensions': ['.js', '.mn'],
                 'find': [sys.executable], 'command': ['{exe}', '{file}']}
        self.assertEqual(languages.problems(entry, True), [])
        self.assertTrue(languages.shared_extensions(entry))
        languages.put(entry)
        self.assertFalse(os.path.isfile(runtimes.user_table_path()))
        languages.save()
        self.assertEqual(runtimes.for_file('a.mn').id, 'mynode')
        self.assertEqual(runtimes.for_file('a.js').id, 'mynode')
        self.assertEqual(runtimes.by_id('mynode').source, 'user')
        self.assertIn('mynode', languages.problems(dict(entry), True)[0])

    def test_a_built_in_language_keeps_only_what_was_changed(self):
        languages = self.page.Languages()
        ruby = languages.find('ruby')
        entry = runtimes.entry_of(ruby)
        entry['find'] = [sys.executable]
        languages.put(entry)
        self.assertEqual(languages.entries, [{'id': 'ruby',
                                              'find': [sys.executable]}])
        languages.save()
        changed = runtimes.by_id('ruby')
        self.assertEqual(changed.source, 'changed')
        self.assertEqual(changed.executable(), sys.executable)
        self.assertEqual(changed.extensions, ['.rb'])
        self.assertEqual(changed.name, 'Ruby')
        # Changing nothing writes nothing; Restore default takes it away.
        languages.put(runtimes.entry_of(runtimes.by_id('lua')))
        self.assertEqual(len(languages.entries), 1)
        self.assertTrue(languages.remove('ruby'))
        languages.save()
        self.assertEqual(runtimes.by_id('ruby').source, 'builtin')
        self.assertTrue(runtimes.by_id('lua').inprocess)

    def test_a_language_switched_off_runs_nothing(self):
        languages = self.page.Languages()
        languages.set_disabled('ruby', True)
        languages.save()
        self.assertIsNone(runtimes.for_file('a.rb'))
        self.assertIsNone(runtimes.by_id('ruby'))
        listed = [r for r in runtimes.all_runtimes(include_disabled=True)
                  if r.id == 'ruby']
        self.assertTrue(listed and listed[0].disabled)
        languages.set_disabled('ruby', False)
        self.assertEqual(languages.entries, [])

    def test_a_bad_entry_is_refused_in_words(self):
        languages = self.page.Languages()
        problems = languages.problems({'id': 'Bad Id'}, True)
        self.assertEqual(len(problems), 3)
        self.assertEqual(languages.problems({'id': 'lua', 'extensions':
                                             ['.lua']}, False), [])

    def test_the_rest_of_the_file_is_kept(self):
        path = self.page.ensure_user_table()
        runtimes.write_user_entries([{'id': 'x', 'extensions': ['.x'],
                                      'command': ['{exe}']}])
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        self.assertIn('_comment', data)
        self.assertEqual(data['runtimes'][0]['id'], 'x')

    def test_the_page_and_the_dialog_are_real_controls(self):
        import wx
        app = wx.GetApp() or wx.App(False)
        frame = wx.Frame(None)
        try:
            panel = self.page.build(frame)
            count = panel.listing.GetItemCount()
            self.assertEqual(count, len(runtimes.all_runtimes()))
            dialog = self.page.LanguageDialog(panel, panel.languages,
                                              panel.languages.find('ruby'))
            dialog.find.SetValue(sys.executable)
            entry, refused = dialog.entry()
            dialog.dialog.Destroy()
            self.assertEqual(refused, [])
            panel.languages.put(entry)
            self.page.save(panel)
            self.assertEqual(runtimes.by_id('ruby').executable(),
                             sys.executable)
            self.page.load(panel)
            self.assertEqual(panel.listing.GetItemCount(), count)
            self.assertIn(sys.executable, self.page.check(
                runtimes.by_id('ruby')))
        finally:
            frame.Destroy()
        del app

    def test_the_component_is_called_polyglot(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'polyglot_component_named', os.path.join(COMPONENT, 'init.py'))
        module = importlib.util.module_from_spec(spec)
        saved = hooks.install
        hooks.install = lambda: []
        try:
            spec.loader.exec_module(module)
        finally:
            hooks.install = saved
        seen = []

        class Manager(object):
            def register_menu_function(self, name, function):
                seen.append(('menu', name))

            def register_settings_category(self, name, *callbacks):
                seen.append(('settings', name))
        saved_start = components.start_all
        components.start_all = lambda manager: []
        try:
            module.add_menu(Manager())
            module.add_settings_category(Manager())
        finally:
            components.start_all = saved_start
        self.assertEqual(seen, [('menu', 'Polyglot'), ('settings', 'Polyglot')])



class ThePolyglotWindowsBehaveLikeTitans(unittest.TestCase):
    """Settings -> Polyglot is a Titan settings page in every respect: every
    settings interface can reach it, and its windows sound like Titan's."""

    def setUp(self):
        from polyglotkit import settings_page, tce_ui
        self.page, self.tce_ui = settings_page, tce_ui
        if os.path.isfile(runtimes.user_table_path()):
            os.remove(runtimes.user_table_path())
        self.played = []
        self._saved_play = tce_ui.play
        tce_ui.play = lambda name, pan=None: self.played.append((name, pan))

    def tearDown(self):
        self.tce_ui.play = self._saved_play
        if os.path.isfile(runtimes.user_table_path()):
            os.remove(runtimes.user_table_path())

    def _frame_with_page(self):
        import wx
        app = wx.GetApp() or wx.App(False)
        frame = wx.Frame(None)
        panel = self.page.build(frame)
        frame.categories = {'Polyglot': panel}
        frame.category_order = ['Polyglot']
        return app, frame, panel

    def test_every_settings_interface_reaches_the_languages(self):
        import wx
        from src.settings import ui_model
        app, frame, panel = self._frame_with_page()
        try:
            model = ui_model.SettingsModel(frame)
            (category,) = model.categories()
            kinds = {item['label']: item for item in category['items']}
            languages = kinds[self.page._("Languages")]
            self.assertEqual(languages['kind'], ui_model.KIND_MULTI)
            table = runtimes.all_runtimes(include_disabled=True)
            self.assertEqual(len(languages['options']), len(table))
            ruby = [o for o in languages['options'] if o.startswith('Ruby')][0]
            self.assertIn(ruby, languages['value'])
            details = kinds[self.page._("Details")]
            self.assertEqual(details['kind'], ui_model.KIND_INFO)
            self.assertIn(self.page._("Language: {}").format(table[0].name),
                          details['value'])
            commands = [i['label'] for i in category['items']
                        if i['kind'] == ui_model.KIND_COMMAND]
            self.assertIn(self.page._("Add a language..."), commands)
            # Unticking a row in an interface switches the language off,
            # and the row keeps its words, so it can be found again.
            item = [i for i in model.items()
                    if i.kind == ui_model.KIND_MULTI][0]
            self.assertTrue(item.set([o for o in languages['options']
                                      if o != ruby]))
            app.ProcessPendingEvents()
            self.assertTrue(panel.languages.find('ruby').disabled)
            self.assertIn(ruby, item.options)
            self.assertEqual(panel.listing.GetString(
                panel.ids.index('ruby')), ruby)
            self.page.save(panel)
            self.assertIsNone(runtimes.by_id('ruby'))
            # An interface picks the language the buttons act on, and reads
            # what Check found under the details.
            model.read()
            target = [i for i in model.items()
                      if i.label == self.page._("Language the buttons act on")][0]
            self.assertEqual(target.kind, ui_model.KIND_CHOICE)
            self.assertTrue(target.set('Lua'))
            app.ProcessPendingEvents()
            self.assertEqual(panel.ids[panel.listing.GetFirstSelected()], 'lua')
            shown = []
            saved = self.tce_ui.message
            self.tce_ui.message = lambda *a, **k: shown.append(a)
            try:
                check = [i for i in model.items()
                         if i.label == self.page._("Check")][0]
                self.assertTrue(check.press())
                app.ProcessPendingEvents()
            finally:
                self.tce_ui.message = saved
            self.assertEqual(len(shown), 1)
            self.assertIn(self.page.check(panel.languages.find('lua')),
                          panel.details.GetValue())
        finally:
            frame.Destroy()
        del app, wx

    def test_every_field_of_the_dialog_is_named_and_grouped(self):
        import wx
        app, frame, panel = self._frame_with_page()
        try:
            dialog = self.page.LanguageDialog(panel, panel.languages,
                                              panel.languages.find('ruby'))
            boxes = [c for c in self.tce_ui._walk(dialog.dialog)
                     if isinstance(c, wx.StaticBox)]
            self.assertEqual(len(boxes), 2)
            for control in self.tce_ui._walk(dialog.dialog):
                if not isinstance(control, wx.TextCtrl) or \
                        control.GetWindowStyleFlag() & wx.TE_READONLY:
                    continue
                self.assertIsInstance(control.GetParent(), wx.StaticBox)
                siblings = list(control.GetParent().GetChildren())
                before = siblings[siblings.index(control) - 1]
                self.assertIsInstance(before, wx.StaticText)
                self.assertTrue(control.GetName())
            dialog.dialog.Destroy()
        finally:
            frame.Destroy()
        del app

    def test_the_windows_sound_like_titan(self):
        self.assertEqual(self.tce_ui.row_pan(0, 5), 0.0)
        self.assertEqual(self.tce_ui.row_pan(4, 5), 1.0)
        self.assertEqual(self.tce_ui.row_pan(0, 1), 0.5)

        class Dialog(object):
            def ShowModal(self):
                return 5100
        self.assertEqual(self.tce_ui.modal(Dialog()), 5100)
        self.assertEqual([n for n, _p in self.played],
                         ['ui/dialog.ogg', 'ui/dialogclose.ogg'])

    def test_a_message_says_what_kind_it_is(self):
        import wx
        from src.accessibility import messages
        told = []
        saved_kind = messages.announce_dialog_kind
        saved_dialog = wx.MessageDialog

        class Answered(object):
            def __init__(self, *args):
                self.args = args

            def ShowModal(self):
                return wx.ID_YES

            def Destroy(self):
                pass
        messages.announce_dialog_kind = told.append
        wx.MessageDialog = Answered
        try:
            self.assertTrue(self.tce_ui.ask(None, 'Remove?', 'Polyglot'))
            self.tce_ui.message(None, 'Broken', 'Polyglot', 'error')
        finally:
            messages.announce_dialog_kind = saved_kind
            wx.MessageDialog = saved_dialog
        self.assertEqual(told, ['question', 'error'])
        self.assertIn('core/error.ogg', [n for n, _p in self.played])

    def test_a_built_in_languages_note_is_said_in_polish(self):
        import gettext
        catalogue = gettext.translation(
            'polyglot', os.path.join(COMPONENT, 'languages'), ['pl'])
        untranslated = [r.note for r in runtimes.builtin()
                        if r.note and catalogue.gettext(r.note) == r.note]
        self.assertEqual(untranslated, [])

    def test_the_invisible_ui_gives_the_keyboard_to_a_polyglot_window(self):
        import wx
        app = wx.GetApp() or wx.App(False)
        frame = wx.Frame(None)
        calls = []

        class Interface(object):
            def temporarily_disable_titan_ui(self, name):
                calls.append(('take', name))

            def _on_dialog_close(self, name, _event):
                calls.append(('give', name))

        class Dialog(object):
            def ShowModal(self):
                calls.append(('shown',))
                return 0
        frame.invisible_ui = Interface()
        try:
            self.tce_ui.modal(Dialog())
        finally:
            frame.Destroy()
        self.assertEqual(calls, [('take', 'polyglot'), ('shown',),
                                 ('give', 'polyglot')])
        del app

    def test_a_list_runs_out_with_titans_sound(self):
        import wx
        app = wx.GetApp() or wx.App(False)
        frame = wx.Frame(None)
        try:
            listing = wx.ListCtrl(frame, style=wx.LC_REPORT)
            listing.InsertColumn(0, 'x')
            for row in range(3):
                listing.InsertItem(row, str(row))
            self.tce_ui.cue_list(listing)
            listing.Focus(2)
            event = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
            event.SetKeyCode(wx.WXK_DOWN)
            listing.GetEventHandler().ProcessEvent(event)
            self.assertIn('ui/endoflist.ogg', [n for n, _p in self.played])
        finally:
            frame.Destroy()
        del app

if __name__ == '__main__':
    try:
        unittest.main(verbosity=1)
    finally:
        shutil.rmtree(_APPDATA, ignore_errors=True)
