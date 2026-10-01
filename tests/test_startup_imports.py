"""What importing ``main`` must NOT load.

Measured before this (2026-09-30): ``import main`` loaded 488 modules and
58 MB - asyncio at line 1 of main.py (10 MB), accessible_output3 through
six different modules (whose ``outputs`` package imports every backend, and
the Window-Eyes one brings speech_recognition, 8.7 MB), a background thread
preloading speech_recognition again, wmi for a watcher nothing starts,
pywinctl and webbrowser for functions nobody had called. After: 354
modules and 44 MB. Each of these is imported the first time it is used.

Run directly: ``python tests/test_startup_imports.py``. The import happens
in a subprocess so the test runner's own imports cannot hide a regression.
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Modules that startup has no business loading. A name that appears here
#: again is a module-level import that should have been a local one.
NOT_AT_STARTUP = [
    'asyncio', 'websockets', 'telethon',
    'accessible_output3', 'speech_recognition',
    'wmi', 'pywinctl', 'webbrowser', 'urllib.request', 'http.client',
]

PROBE = r"""
import os, sys, json
sys.path.insert(0, %r); os.chdir(%r)
import main
print("PROBE:" + json.dumps({
    "loaded": [m for m in %r if m in sys.modules],
    "count": len(sys.modules),
    "loop_set": bool(sys.modules.get('asyncio')),
}))
"""


class ImportingMainLoadsOnlyWhatItUses(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        env = dict(os.environ, PYTHONUTF8='1')
        result = subprocess.run(
            [sys.executable, '-c', PROBE % (ROOT, ROOT, NOT_AT_STARTUP)],
            capture_output=True, text=True, timeout=300, env=env, cwd=ROOT)
        lines = [line for line in result.stdout.splitlines() if line.startswith('PROBE:')]
        if not lines:
            raise AssertionError('the probe did not answer:\n' + result.stderr[-2000:])
        cls.answer = json.loads(lines[-1][len('PROBE:'):])

    def test_none_of_the_heavy_libraries_is_loaded(self):
        self.assertEqual(self.answer['loaded'], [])

    def test_the_module_count_stays_down(self):
        # 488 before; a jump back over 400 is a heavy import creeping in.
        self.assertLess(self.answer['count'], 400)


if __name__ == '__main__':
    unittest.main(verbosity=2)
