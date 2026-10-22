"""TInterpreter.TDL: site-packages in one file, unpacked on first import.

Run directly: python tests/test_tdl.py

Each test builds a small site-packages that has every shape the real one
has - an ordinary package with package data, a namespace package filled by
two distributions, a .pth with a path line and an import line (pywin32's
shape), a folder of DLLs with no __init__ (pywin32_system32's), metadata,
a distribution excluded as a build tool, a file pruned for another
platform - packs it, and imports from it in a FRESH interpreter, because
that is where the finder lives in a compiled Titan.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'src', 'titan_core'))
import tdl  # noqa: E402


def _write(base, rel, text=''):
    path = os.path.join(base, rel.replace('/', os.sep))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = 'wb' if isinstance(text, bytes) else 'w'
    with open(path, mode) as handle:
        handle.write(text)
    return rel


def _dist(base, name, version, files):
    # a wheel escapes the name in the folder: Alpha-Pkg -> Alpha_Pkg
    info = f"{name.replace('-', '_')}-{version}.dist-info"
    _write(base, f'{info}/METADATA', f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n')
    record = [f'{rel},,' for rel in files] + [f'{info}/METADATA,,', f'{info}/RECORD,,']
    _write(base, f'{info}/RECORD', '\n'.join(record) + '\n')


def make_site(base):
    files = [
        _write(base, 'alpha/__init__.py', 'from .core import VALUE\n'),
        _write(base, 'alpha/core.py', 'import os\nVALUE = 42\n'
               'DATA = open(os.path.join(os.path.dirname(__file__), "data.txt")).read()\n'),
        _write(base, 'alpha/data.txt', 'hello from data'),
        _write(base, 'alpha_tool.py', 'NAME = "tool"\n'),
    ]
    _dist(base, 'Alpha-Pkg', '1.2.3', files)
    _dist(base, 'space-one', '1.0',
          [_write(base, 'space/one/__init__.py', 'X = 1\n')])
    _dist(base, 'space-two', '2.0',
          [_write(base, 'space/two/__init__.py', 'X = 2\n')])
    pw = [
        _write(base, 'pw/lib/pw_bootstrap.py',
               'import os\nos.environ["PW_BOOTSTRAPPED"] = "yes"\n'),
        _write(base, 'pw/pwapi.py', 'API = "pwapi"\n'),
        _write(base, 'pw_system32/pwtypes.dll', b'MZ' + b'\0' * 64),
        _write(base, 'pw.pth', 'pw\npw\\lib\n# comment\nimport pw_bootstrap\n'),
    ]
    _dist(base, 'pw', '300', pw)
    _dist(base, 'Nuitka', '2.0', [_write(base, 'nuitka/__init__.py', '')])
    _write(base, 'loose_module.py', 'LOOSE = True\n')
    _write(base, 'speech_recognition/__init__.py', 'SR = 1\n')
    _write(base, 'speech_recognition/flac-mac', b'\0' * 10)
    _write(base, 'alpha/__pycache__/core.cpython-99.pyc', b'junk')


def run_python(code, tdl_path, cache, first_on_path=None):
    env = dict(os.environ)
    env['PYTHONPATH'] = os.path.join(ROOT, 'src', 'titan_core')
    prelude = (f"import tdl, sys; f = tdl.install({tdl_path!r}, cache={cache!r}); "
               "assert f is not None, 'not installed'\n")
    if first_on_path:
        prelude += f"sys.path.insert(0, {first_on_path!r})\n"
    result = subprocess.run([sys.executable, '-I', '-c',
                             f"import sys; sys.path.insert(0, {env['PYTHONPATH']!r})\n"
                             + prelude + code],
                            capture_output=True, text=True, env=env, timeout=120)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout.strip()


class TheTdlIsBuiltAndRead(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='tdltest_')
        cls.site = os.path.join(cls.tmp, 'site-packages')
        make_site(cls.site)
        cls.path = os.path.join(cls.tmp, 'T.TDL')
        cls.index = tdl.build([cls.site], cls.path, preset=1,
                              log=lambda *a: None)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def cache(self):
        return tempfile.mkdtemp(prefix='cache_', dir=self.tmp)

    def test_one_unit_per_distribution(self):
        units = set(self.index['units'])
        for unit in ('alpha_pkg', 'space_one', 'space_two', 'pw'):
            self.assertIn(unit, units)

    def test_a_build_tool_is_not_shipped(self):
        self.assertNotIn('nuitka', self.index['units'])
        self.assertNotIn('nuitka', self.index['modules'])

    def test_other_platforms_and_pycache_are_pruned(self):
        listed = [rel for files in tdl.TDL(self.path).lists().values()
                  for rel, *_ in files]
        self.assertNotIn('alpha/__pycache__/core.cpython-99.pyc', listed)
        if sys.platform.startswith('win'):
            self.assertNotIn('speech_recognition/flac-mac', listed)
        self.assertIn('alpha/data.txt', listed)

    def test_every_unit_decompresses_whole(self):
        self.assertEqual(tdl.TDL(self.path).check(), [])

    def test_a_package_imports_with_its_data(self):
        out = run_python("import alpha, alpha.core; print(alpha.VALUE, alpha.core.DATA)",
                         self.path, self.cache())
        self.assertEqual(out, '42 hello from data')

    def test_nothing_is_unpacked_that_was_not_imported(self):
        cache = self.cache()
        run_python("import alpha_tool", self.path, cache)
        marks = sorted(os.listdir(os.path.join(cache, '.units')))
        self.assertEqual([m for m in marks if m.endswith('.ok')], ['alpha_pkg.ok'])
        self.assertFalse(os.path.exists(os.path.join(cache, 'site-packages', 'pw')))

    def test_a_namespace_is_filled_one_distribution_at_a_time(self):
        cache = self.cache()
        out = run_python("import space.two as t; print(t.X)", self.path, cache)
        self.assertEqual(out, '2')
        marks = os.listdir(os.path.join(cache, '.units'))
        self.assertIn('space_two.ok', marks)
        self.assertNotIn('space_one.ok', marks)
        out = run_python("import space.one, space.two; print(space.one.X + space.two.X)",
                         self.path, cache)
        self.assertEqual(out, '3')

    def test_metadata_is_found_before_the_package_is_imported(self):
        out = run_python("import importlib.metadata as m; print(m.version('alpha-pkg'))",
                         self.path, self.cache())
        self.assertEqual(out, '1.2.3')

    def test_a_pth_root_and_its_import_line(self):
        cache = self.cache()
        code = ("import os, pwapi; print(pwapi.API, os.environ.get('PW_BOOTSTRAPPED'))")
        self.assertEqual(run_python(code, self.path, cache), 'pwapi yes')
        # the next process finds it unpacked and still runs the import line
        self.assertEqual(run_python(code, self.path, cache), 'pwapi yes')

    def test_a_dll_folder_goes_on_the_search_path(self):
        out = run_python("import pwapi, os; print(os.environ['PATH'].split(os.pathsep)[0])",
                         self.path, self.cache())
        self.assertTrue(out.endswith('pw_system32'), out)

    def test_a_frozen_half_package_earlier_on_the_path_does_not_hide_it(self):
        # PyInstaller leaves _internal/wx/ with only wx's .pyd files and no
        # __init__, and _internal is first on python.exe's path: a namespace
        # portion that must not stand in for the real package.
        frozen = tempfile.mkdtemp(prefix='frozen_', dir=self.tmp)
        _write(frozen, 'alpha/_speedups.pyd', b'MZ')
        out = run_python("import alpha; print(alpha.VALUE, alpha.__file__ is not None)",
                         self.path, self.cache(), first_on_path=frozen)
        self.assertEqual(out, '42 True')

    def test_an_applications_own_copy_still_wins(self):
        own = tempfile.mkdtemp(prefix='own_', dir=self.tmp)
        _write(own, 'alpha/__init__.py', 'VALUE = "mine"\n')
        out = run_python("import alpha; print(alpha.VALUE)",
                         self.path, self.cache(), first_on_path=own)
        self.assertEqual(out, 'mine')

    def test_warm_unpacks_without_importing(self):
        cache = self.cache()
        out = run_python("import sys; tdl.warm(['alpha', 'nothing_here']); "
                         "print('alpha' in sys.modules)", self.path, cache)
        self.assertEqual(out, 'False')
        self.assertIn('alpha_pkg.ok', os.listdir(os.path.join(cache, '.units')))

    def test_a_missing_module_is_still_missing(self):
        out = run_python("try:\n    import no_such_thing\nexcept ImportError:\n    print('missing')",
                         self.path, self.cache())
        self.assertEqual(out, 'missing')

    def test_a_loose_file_is_its_own_unit(self):
        out = run_python("import loose_module; print(loose_module.LOOSE)",
                         self.path, self.cache())
        self.assertEqual(out, 'True')

    def test_two_processes_at_once_unpack_once(self):
        cache = self.cache()
        code = "import alpha; print(alpha.VALUE)"
        env = dict(os.environ)
        script = (f"import sys; sys.path.insert(0, {os.path.join(ROOT, 'src', 'titan_core')!r})\n"
                  f"import tdl; tdl.install({self.path!r}, cache={cache!r})\n" + code)
        procs = [subprocess.Popen([sys.executable, '-I', '-c', script],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, env=env) for _ in range(4)]
        outs = [p.communicate(timeout=120) for p in procs]
        for (out, err), p in zip(outs, procs):
            self.assertEqual(p.returncode, 0, err)
            self.assertEqual(out.strip(), '42')
        leftovers = [n for folder, _d, files in os.walk(cache) for n in files
                     if n.endswith('.tmp')]
        self.assertEqual(leftovers, [])

    def test_an_interpreter_of_another_version_does_not_use_it(self):
        broken = os.path.join(self.tmp, 'other.TDL')
        index = dict(tdl.TDL(self.path).index)
        index['tag'] = 'cpython-01'
        import marshal, struct
        with open(self.path, 'rb') as handle:
            body = handle.read()
        at = struct.unpack('<Q', body[4:12])[0]
        with open(broken, 'wb') as handle:
            handle.write(body[:at] + marshal.dumps(index))
        self.assertIsNone(tdl.install(broken, cache=self.cache()))



class TheInterpreterIsBuilt(unittest.TestCase):
    """src/scripts/build_interpreter.py on a small _internal."""

    def setUp(self):
        sys.path.insert(0, os.path.join(ROOT, 'src', 'scripts'))
        import build_interpreter
        self.bi = build_interpreter
        self.dist = tempfile.mkdtemp(prefix='tdldist_')
        internal = os.path.join(self.dist, '_internal')
        _write(internal, 'Lib/os.py', 'X = 1\n')
        _write(internal, 'Lib/json/__init__.py', 'Y = 2\n')
        _write(internal, 'Lib/idlelib/__init__.py', '')
        _write(internal, 'Lib/pydoc_data/topics.txt', 'data')
        make_site(os.path.join(internal, 'Lib', 'site-packages'))
        _write(internal, 'speech_recognition/pocketsphinx-data/x.bin', b'0' * 100)
        self.internal = internal

    def tearDown(self):
        shutil.rmtree(self.dist, ignore_errors=True)

    def build(self):
        self.bi.build(self.dist, fast=True, log=lambda *a: None)

    def test_the_tree_it_leaves(self):
        self.build()
        import zipfile
        names = zipfile.ZipFile(os.path.join(
            self.internal, f'python{self.bi.python_tag()}.zip')).namelist()
        self.assertIn('os.pyc', names)
        self.assertIn('json/__init__.pyc', names)
        self.assertIn('pydoc_data/topics.txt', names)
        self.assertFalse(any(n.startswith('idlelib') for n in names))
        # the loader stays a real file, never a stale copy in the zip
        self.assertFalse(any(n.startswith('titan_tdl') for n in names))
        self.assertTrue(os.path.isfile(os.path.join(self.internal, 'Lib', 'titan_tdl.py')))
        self.assertEqual(sorted(os.listdir(os.path.join(self.internal, 'Lib', 'site-packages'))),
                         ['titan_tdl.pth'])
        self.assertTrue(os.path.isfile(os.path.join(self.internal, tdl.FILE_NAME)))
        self.assertFalse(os.path.exists(os.path.join(
            self.internal, 'speech_recognition', 'pocketsphinx-data')))

    def test_a_second_run_keeps_the_standard_library(self):
        self.build()
        zip_path = os.path.join(self.internal, f'python{self.bi.python_tag()}.zip')
        size = os.path.getsize(zip_path)
        tdl_size = os.path.getsize(os.path.join(self.internal, tdl.FILE_NAME))
        self.build()
        self.assertEqual(os.path.getsize(zip_path), size)
        self.assertEqual(os.path.getsize(os.path.join(self.internal, tdl.FILE_NAME)), tdl_size)


if __name__ == '__main__':
    unittest.main()
