"""Nothing under src breaks another platform at import time.

``.claude/skills/bug-fixer/scripts/check_platform.py`` walks every module
for a Windows-only import or a ``ctypes.windll`` read that is not behind a
platform test or a ``try`` - the two shapes that made a module raise the
moment Linux or macOS imported it (``winreg`` in file_association,
``WINFUNCTYPE`` in wlan). Measured on a Linux Python 3.12 in WSL with a
wx stand-in: 217 of 222 modules under src imported before this, and every
one of them after, the rest being libraries not installed there.

Run directly: ``python tests/test_platform_imports.py``.
"""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKER = os.path.join(ROOT, '.claude', 'skills', 'bug-fixer', 'scripts', 'check_platform.py')


class NothingBreaksAnotherPlatformAtImport(unittest.TestCase):

    def _run(self, *roots):
        result = subprocess.run([sys.executable, CHECKER, *roots], cwd=ROOT,
                                capture_output=True, text=True, timeout=300)
        return result.returncode, result.stdout

    def test_src_and_main(self):
        code, out = self._run('src', 'main.py')
        problems = [l for l in out.splitlines() if ': ' in l and l[0] != '\n'
                    and not l.endswith('problem(s).')]
        # check_capture.py is a Windows-only probe run by hand; everything
        # else must be clean.
        problems = [p for p in problems if 'check_capture.py' not in p]
        self.assertEqual(problems, [])

    def test_every_add_on_kind(self):
        code, out = self._run('data/components', 'data/applications', 'data/applets',
                              'data/gamepad', 'data/launchers', 'data/titantts engines',
                              'data/shell addons', 'data/settings interfaces')
        problems = [l for l in out.splitlines() if ': ' in l and not l.endswith('problem(s).')]
        self.assertEqual(problems, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
