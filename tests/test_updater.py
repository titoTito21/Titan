"""What the updater must never do again.

The bug these tests exist for: ``_stage_locked_targets`` renames every file
the archive will overwrite to ``<name>.old``, and the archive contains
``data/bin/7z.exe`` and ``data/bin/7z.dll`` like everything else - so the
extractor renamed ITSELF aside and the next line launched a file that no
longer existed. Every compiled update failed with ``[WinError 2]``, was
rolled back, and was reported as "Update failed. Please try again later.".

Run directly: ``python tests/test_updater.py`` (tests/ has no __init__.py).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.system import updater as updater_module
from src.scripts import titan_updater as standalone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEVEN_ZIP_SOURCE = os.path.join(REPO, 'data', 'bin', '7z.exe')
SEVEN_DLL_SOURCE = os.path.join(REPO, 'data', 'bin', '7z.dll')

HAVE_7Z = os.path.exists(SEVEN_ZIP_SOURCE)


class Recorder:
    """Stands in for the progress dialog; keeps what it was told."""

    def __init__(self):
        self.updates = []

    def update_progress(self, percent, text=None):
        self.updates.append((percent, text))


def build_install(root, exe_body=b'old titan'):
    """An install shaped like the real one: Titan.exe plus data/bin/7z.exe."""
    install = os.path.join(root, 'install')
    os.makedirs(os.path.join(install, 'data', 'bin'))
    shutil.copy(SEVEN_ZIP_SOURCE, os.path.join(install, 'data', 'bin', '7z.exe'))
    shutil.copy(SEVEN_DLL_SOURCE, os.path.join(install, 'data', 'bin', '7z.dll'))
    with open(os.path.join(install, 'Titan.exe'), 'wb') as handle:
        handle.write(exe_body)
    return install


def build_archive(root, name='titan_update.7z', include_seven_zip=True,
                  exe_body=b'new titan'):
    """An archive shaped like titan.main.7z - it replaces 7-Zip as well."""
    staging = os.path.join(root, 'newver')
    os.makedirs(os.path.join(staging, 'data', 'bin'), exist_ok=True)
    with open(os.path.join(staging, 'Titan.exe'), 'wb') as handle:
        handle.write(exe_body)
    if include_seven_zip:
        shutil.copy(SEVEN_ZIP_SOURCE, os.path.join(staging, 'data', 'bin', '7z.exe'))
        shutil.copy(SEVEN_DLL_SOURCE, os.path.join(staging, 'data', 'bin', '7z.dll'))

    archive = os.path.join(root, name)
    subprocess.run([SEVEN_ZIP_SOURCE, 'a', '-t7z', archive, '*'],
                   cwd=staging, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    return archive


def make_updater(install, archive):
    """An Updater wired to a sandbox, without touching the network."""
    instance = updater_module.Updater.__new__(updater_module.Updater)
    instance.install_dir = install
    instance.seven_zip_path = os.path.join(install, 'data', 'bin', '7z.exe')
    instance.temp_file = archive
    instance.temp_interpreter_file = archive + '.interpreter'
    instance._extractor = None
    instance._extractor_dir = None
    instance.needs_interpreter = False
    return instance


@unittest.skipUnless(HAVE_7Z, "data/bin/7z.exe is not present")
class ExtractorStandsOutside(unittest.TestCase):
    """The tool doing the work must not be a file the work replaces."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='titan_updater_test_')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        # Every test here is about the compiled build - the dev build stages
        # nothing at all.
        self._was_frozen = updater_module.is_frozen
        updater_module.is_frozen = lambda: True
        self.addCleanup(self._restore_frozen)

    def _restore_frozen(self):
        updater_module.is_frozen = self._was_frozen

    def test_extractor_is_copied_out_of_the_install(self):
        install = build_install(self.root)
        archive = build_archive(self.root)
        instance = make_updater(install, archive)
        self.addCleanup(instance._release_extractor)

        resolved = instance._resolve_extractor()
        self.assertTrue(os.path.exists(resolved))
        self.assertFalse(
            instance._inside_install(resolved),
            "the extractor is still inside the tree it is about to rewrite")

    def test_extraction_succeeds_although_the_archive_replaces_7zip(self):
        """The regression itself, end to end."""
        install = build_install(self.root)
        archive = build_archive(self.root, include_seven_zip=True)
        instance = make_updater(install, archive)

        self.assertTrue(
            instance._extract_archive(archive, Recorder(), 'extracting'),
            "extraction failed - the updater renamed its own 7-Zip aside")

        with open(os.path.join(install, 'Titan.exe'), 'rb') as handle:
            self.assertEqual(handle.read(), b'new titan')
        # The old copy is kept for cleanup_old_update_files() at next start.
        self.assertTrue(os.path.exists(os.path.join(install, 'Titan.exe.old')))
        # And 7-Zip itself was replaced, not merely moved away.
        self.assertTrue(
            os.path.exists(os.path.join(install, 'data', 'bin', '7z.exe')))

    def test_the_temporary_copy_is_removed(self):
        install = build_install(self.root)
        archive = build_archive(self.root)
        instance = make_updater(install, archive)

        directory = os.path.dirname(instance._resolve_extractor())
        self.assertTrue(os.path.isdir(directory))
        instance._release_extractor()
        self.assertFalse(os.path.isdir(directory))

    def test_a_7zip_outside_the_install_is_used_where_it_stands(self):
        """Nothing is copied when there is nothing to protect it from."""
        install = build_install(self.root)
        outside = os.path.join(self.root, 'elsewhere')
        os.makedirs(outside)
        shutil.copy(SEVEN_ZIP_SOURCE, os.path.join(outside, '7z.exe'))

        instance = make_updater(install, os.path.join(self.root, 'x.7z'))
        instance.seven_zip_path = os.path.join(outside, '7z.exe')
        self.addCleanup(instance._release_extractor)

        self.assertEqual(instance._resolve_extractor(),
                         os.path.join(outside, '7z.exe'))

    def test_staging_leaves_an_in_tree_extractor_alone(self):
        """The belt to the braces: if the copy could not be made, staging
        must not move the 7-Zip that is about to be launched."""
        install = build_install(self.root)
        archive = build_archive(self.root, include_seven_zip=True)
        instance = make_updater(install, archive)
        # Force the fallback: pretend copying out failed.
        instance._extractor = os.path.join(install, 'data', 'bin', '7z.exe')

        staged = instance._stage_locked_targets(archive)
        self.addCleanup(instance._rollback_staging, staged)

        self.assertTrue(os.path.exists(instance._extractor),
                        "the extractor was renamed away and cannot be run")
        moved = [target for kind, _old, target in staged if kind == 'rename']
        self.assertNotIn(instance._extractor, moved)

    def test_a_failed_extraction_leaves_the_install_untouched(self):
        install = build_install(self.root)
        broken = os.path.join(self.root, 'broken.7z')
        # A real archive, truncated: 7-Zip fails and rollback must run.
        good = build_archive(self.root, name='good.7z')
        with open(good, 'rb') as source, open(broken, 'wb') as target:
            target.write(source.read()[:200])

        instance = make_updater(install, broken)
        self.assertFalse(
            instance._extract_archive(broken, Recorder(), 'extracting'))

        with open(os.path.join(install, 'Titan.exe'), 'rb') as handle:
            self.assertEqual(handle.read(), b'old titan')
        self.assertTrue(
            os.path.exists(os.path.join(install, 'data', 'bin', '7z.exe')))
        self.assertFalse(os.path.exists(os.path.join(install, 'Titan.exe.old')))


@unittest.skipUnless(HAVE_7Z, "data/bin/7z.exe is not present")
class StandaloneUpdater(unittest.TestCase):
    """The repair tool for the Titans that cannot update themselves."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='titan_standalone_test_')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_it_updates_an_install(self):
        install = build_install(self.root)
        archive = build_archive(self.root)

        update = standalone.TitanUpdate(install)
        self.addCleanup(update.release)
        self.assertTrue(update.run([archive]))

        with open(os.path.join(install, 'Titan.exe'), 'rb') as handle:
            self.assertEqual(handle.read(), b'new titan')

    def test_it_needs_no_7zip_inside_the_install(self):
        """The install may be the very thing that is broken."""
        install = build_install(self.root)
        archive = build_archive(self.root, include_seven_zip=False)
        shutil.rmtree(os.path.join(install, 'data', 'bin'))

        update = standalone.TitanUpdate(install)
        self.addCleanup(update.release)
        # Stand in for the copy a compiled build carries with it.
        original = standalone.bundled_dir
        standalone.bundled_dir = lambda: os.path.dirname(SEVEN_ZIP_SOURCE)
        self.addCleanup(setattr, standalone, 'bundled_dir', original)

        self.assertTrue(update.run([archive]))
        with open(os.path.join(install, 'Titan.exe'), 'rb') as handle:
            self.assertEqual(handle.read(), b'new titan')

    def test_it_refuses_a_folder_that_is_not_titan(self):
        empty = os.path.join(self.root, 'not_titan')
        os.makedirs(empty)
        with self.assertRaises(standalone.UpdateError):
            standalone.TitanUpdate(empty).check_install()

    def test_a_failure_puts_everything_back(self):
        install = build_install(self.root)
        good = build_archive(self.root, name='good.7z')
        broken = os.path.join(self.root, 'broken.7z')
        with open(good, 'rb') as source, open(broken, 'wb') as target:
            target.write(source.read()[:200])

        update = standalone.TitanUpdate(install)
        self.addCleanup(update.release)
        with self.assertRaises(standalone.UpdateError):
            update.run([broken])

        with open(os.path.join(install, 'Titan.exe'), 'rb') as handle:
            self.assertEqual(handle.read(), b'old titan')
        self.assertFalse(os.path.exists(os.path.join(install, 'Titan.exe.old')))

    def test_the_program_is_unpacked_before_the_interpreter(self):
        install = build_install(self.root)
        for name in ('titan.interpreter.7z', 'titan.main.7z'):
            with open(os.path.join(install, name), 'wb') as handle:
                handle.write(b'')
        found = [os.path.basename(p)
                 for p in standalone.find_archives(install)]
        self.assertLess(found.index('titan.main.7z'),
                        found.index('titan.interpreter.7z'))

    def test_cleanup_removes_staged_files_and_nothing_else(self):
        install = build_install(self.root)
        staged = os.path.join(install, 'Titan.exe.old')
        numbered = os.path.join(install, 'Titan.exe.old12')
        orphan = os.path.join(install, 'gone.exe.old')
        user_file = os.path.join(install, 'notes.older.txt')
        for path in (staged, numbered, orphan, user_file):
            with open(path, 'wb') as handle:
                handle.write(b'x')

        standalone.TitanUpdate(install).clean_old()

        self.assertFalse(os.path.exists(staged))
        self.assertFalse(os.path.exists(numbered))
        # No live counterpart - not one of ours, so not ours to delete.
        self.assertTrue(os.path.exists(orphan))
        self.assertTrue(os.path.exists(user_file))

    def test_it_says_which_archive_does_not_exist(self):
        install = build_install(self.root)
        with self.assertRaises(standalone.UpdateError):
            standalone.find_archives(install, ['no_such_archive.7z'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
