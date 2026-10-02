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

import atexit as _atexit

#: Temporary directories this run made, removed when it ends.
#:
#: Measured: this suite left 2 directories behind per run, one per `mkdtemp` that
#: nothing removed, and they accumulate for ever - thousands had built up in
#: %TEMP%. Registered at exit rather than per test so a FAILING test cleans
#: up too.
_SCRATCH = []


def _sweep_old_extractors():
    """Remove the private 7-Zip copies earlier runs left behind.

    `UpdateManager._resolve_extractor` makes one in %TEMP% and
    `_release_extractor` removes it - production is correct and guarded
    against resolving twice. A couple of tests reach the resolver by a path
    that does not release, so two `titan_update_7z_*` directories are left per
    run. Sweeping at the start bounds that at one run's worth instead of
    letting it grow, without touching the production path to suit a test.
    """
    here = tempfile.gettempdir()
    try:
        names = os.listdir(here)
    except OSError:
        return
    for name in names:
        if name.startswith('titan_update_7z_'):
            shutil.rmtree(os.path.join(here, name), ignore_errors=True)


_sweep_old_extractors()


def scratch(prefix=None):
    """A temporary directory that is removed when the run ends."""
    path = tempfile.mkdtemp(**({'prefix': prefix} if prefix else {}))
    _SCRATCH.append(path)
    return path


@_atexit.register
def _clear_scratch():
    while _SCRATCH:
        shutil.rmtree(_SCRATCH.pop(), ignore_errors=True)


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
                  exe_body=b'new titan', extra=None):
    """An archive shaped like titan.main.7z - it replaces 7-Zip as well.
    ``extra`` maps further relative paths to their contents."""
    staging = os.path.join(root, 'newver')
    os.makedirs(os.path.join(staging, 'data', 'bin'), exist_ok=True)
    with open(os.path.join(staging, 'Titan.exe'), 'wb') as handle:
        handle.write(exe_body)
    for rel, body in (extra or {}).items():
        path = os.path.join(staging, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as handle:
            handle.write(body)
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
        self.root = scratch('titan_updater_test_')
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


try:
    import py7zr as _py7zr
    HAVE_PY7ZR = True
except Exception:
    HAVE_PY7ZR = False


@unittest.skipUnless(HAVE_7Z and HAVE_PY7ZR, "needs 7z.exe to build the "
                                             "archive and py7zr to read it")
class NoBinaryNeeded(unittest.TestCase):
    """Titan unpacks the update itself, with no external program at all.

    This is the structural half of the fix: an extractor that lives inside
    the directory being rewritten is an extractor the update can rename out
    from under itself. py7zr cannot be renamed away because it is not a file
    on the way to being replaced - it is already in memory.
    """

    def setUp(self):
        self.root = scratch('titan_updater_nobin_')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self._was_frozen = updater_module.is_frozen
        updater_module.is_frozen = lambda: True
        self.addCleanup(lambda: setattr(updater_module, 'is_frozen',
                                        self._was_frozen))

    def test_it_extracts_with_no_7zip_anywhere(self):
        """The real no-binary case: nothing in data/bin and nothing on PATH."""
        install = build_install(self.root)
        archive = build_archive(self.root, include_seven_zip=False)
        shutil.rmtree(os.path.join(install, 'data', 'bin'))

        instance = make_updater(install, archive)
        self.addCleanup(instance._release_extractor)
        # No 7-Zip installed on the machine either.
        was_which = updater_module.shutil.which
        updater_module.shutil.which = lambda name: None
        self.addCleanup(setattr, updater_module.shutil, 'which', was_which)

        self.assertTrue(
            instance._extract_archive(archive, Recorder(), 'extracting'))
        with open(os.path.join(install, 'Titan.exe'), 'rb') as handle:
            self.assertEqual(handle.read(), b'new titan')
        # And no external program was there to do it.
        self.assertFalse(instance._extractor
                         and os.path.exists(instance._extractor))

    def test_the_listing_matches_7zip(self):
        """The staging decisions must not depend on who read the archive."""
        install = build_install(self.root)
        archive = build_archive(self.root)
        instance = make_updater(install, archive)
        self.addCleanup(instance._release_extractor)

        from_py7zr = sorted(instance._archive_entries_py7zr(archive))
        instance._archive_entries_py7zr = lambda path: None
        from_binary = sorted(instance._list_archive_entries(archive))

        def normalised(entries):
            # The two readers disagree only about the separator, and the
            # staging code normalises that itself.
            return [(path.replace(os.sep, '/'), is_dir)
                    for path, is_dir in entries]

        self.assertEqual(normalised(from_py7zr), normalised(from_binary))

    def test_a_missing_py7zr_still_updates_through_7zip(self):
        """The fallback is the one that must never quietly disappear.

        With NO 7-Zip on PATH: the one in the install is the only one, and
        staging renames it away - so the copy made of it has to exist
        BEFORE staging runs. It did not, and this test passed anyway on a
        machine with a 7-Zip in Program Files while every compiled update
        on a machine without one failed.
        """
        install = build_install(self.root)
        archive = build_archive(self.root)
        instance = make_updater(install, archive)
        instance._extract_with_py7zr = lambda *a, **k: False
        instance._archive_entries_py7zr = lambda path: None
        self.addCleanup(instance._release_extractor)
        was_which = updater_module.shutil.which
        updater_module.shutil.which = lambda name: None
        self.addCleanup(setattr, updater_module.shutil, 'which', was_which)

        self.assertTrue(
            instance._extract_archive(archive, Recorder(), 'extracting'))
        with open(os.path.join(install, 'Titan.exe'), 'rb') as handle:
            self.assertEqual(handle.read(), b'new titan')


@unittest.skipUnless(HAVE_7Z, "data/bin/7z.exe is not present")
class StandaloneUpdater(unittest.TestCase):
    """The repair tool for the Titans that cannot update themselves."""

    def setUp(self):
        self.root = scratch('titan_standalone_test_')
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


def build_arm64_archive(root, name='arm64.7z', exe_body=b'new titan'):
    """An archive py7zr cannot decode: 7-Zip's ARM64 branch filter.

    The real titan.main.7z of 2026-10-02 carried two ARM64 DLLs
    (sounddevice's portaudio binaries) in a block with exactly this filter,
    and py7zr 1.1.3 answers it with UnsupportedCompressionMethodError. The
    filter is forced here because this suite has no ARM64 PE to make 7-Zip
    choose it by itself.
    """
    staging = os.path.join(root, 'newver_arm64')
    os.makedirs(os.path.join(staging, 'data', 'bin'), exist_ok=True)
    with open(os.path.join(staging, 'Titan.exe'), 'wb') as handle:
        handle.write(exe_body)
    with open(os.path.join(staging, 'data', 'notes.txt'), 'wb') as handle:
        handle.write(b'new notes')
    shutil.copy(SEVEN_ZIP_SOURCE, os.path.join(staging, 'data', 'bin', '7z.exe'))
    shutil.copy(SEVEN_DLL_SOURCE, os.path.join(staging, 'data', 'bin', '7z.dll'))
    archive = os.path.join(root, name)
    subprocess.run([SEVEN_ZIP_SOURCE, 'a', '-t7z', '-mf=ARM64', archive, '*'],
                   cwd=staging, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    return archive


def _no_seven_zip_on_path(test):
    was_which = updater_module.shutil.which
    updater_module.shutil.which = lambda name: None
    test.addCleanup(setattr, updater_module.shutil, 'which', was_which)


def _log_into(test):
    """Send the updater's log into a folder of the test's own; return its path."""
    folder = scratch('titan_updater_log_')
    was = updater_module.log_dir
    updater_module.log_dir = lambda: folder
    test.addCleanup(setattr, updater_module, 'log_dir', was)
    return os.path.join(folder, updater_module.LOG_NAME)


@unittest.skipUnless(HAVE_7Z and HAVE_PY7ZR, "needs 7z.exe and py7zr")
class AnArchivePy7zrCannotRead(unittest.TestCase):
    """The update of 2026-10-02: py7zr imported fine and could not decode
    the archive, and the fallback had been renamed away by then."""

    def setUp(self):
        self.root = scratch('titan_updater_arm64_')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self._was_frozen = updater_module.is_frozen
        updater_module.is_frozen = lambda: True
        self.addCleanup(lambda: setattr(updater_module, 'is_frozen',
                                        self._was_frozen))
        self.log = _log_into(self)

    def test_the_question_is_asked_of_the_header(self):
        install = build_install(self.root)
        plain = build_archive(self.root)
        arm64 = build_arm64_archive(self.root)
        instance = make_updater(install, plain)

        self.assertEqual(instance._py7zr_can_unpack(plain), (True, None))
        can, why = instance._py7zr_can_unpack(arm64)
        self.assertFalse(can)
        self.assertIn('ARM64', why)
        # Nothing was extracted or renamed by asking.
        self.assertFalse(os.path.exists(os.path.join(install, 'Titan.exe.old')))

    def test_it_is_unpacked_by_7zip_with_none_on_path(self):
        """The install's own 7-Zip is the only one, the archive replaces it,
        and py7zr cannot read the archive - the real combination."""
        install = build_install(self.root)
        archive = build_arm64_archive(self.root)
        instance = make_updater(install, archive)
        self.addCleanup(instance._release_extractor)
        _no_seven_zip_on_path(self)

        self.assertTrue(
            instance._extract_archive(archive, Recorder(), 'extracting'))
        with open(os.path.join(install, 'Titan.exe'), 'rb') as handle:
            self.assertEqual(handle.read(), b'new titan')
        self.assertTrue(
            os.path.exists(os.path.join(install, 'data', 'bin', '7z.exe')))
        with open(self.log, encoding='utf-8') as handle:
            text = handle.read()
        self.assertIn('ARM64', text)
        self.assertIn('unpacking with 7-Zip instead', text)

    def test_with_no_7zip_anywhere_nothing_is_touched(self):
        """Refused BEFORE staging, with both reasons, and the install is
        exactly as it was - not rolled back, never changed."""
        install = build_install(self.root)
        archive = build_arm64_archive(self.root)
        shutil.rmtree(os.path.join(install, 'data', 'bin'))
        instance = make_updater(install, archive)
        self.addCleanup(instance._release_extractor)
        _no_seven_zip_on_path(self)
        instance._stage_locked_targets = lambda path: self.fail(
            "staging ran although nothing could unpack the archive")

        self.assertFalse(
            instance._extract_archive(archive, Recorder(), 'extracting'))
        self.assertIn('ARM64', instance.failure_reason)
        self.assertIn('7-Zip', instance.failure_reason)
        with open(os.path.join(install, 'Titan.exe'), 'rb') as handle:
            self.assertEqual(handle.read(), b'old titan')
        self.assertFalse(os.path.exists(os.path.join(install, 'Titan.exe.old')))
        self.assertIn(instance.failure_reason, instance.failure_message())
        self.assertIn(self.log, instance.failure_message())


@unittest.skipUnless(HAVE_7Z, "data/bin/7z.exe is not present")
class AFileTheRunningProgramHoldsOpen(unittest.TestCase):
    """Windows refuses to rename a file any handle has open without
    FILE_SHARE_DELETE - and an ordinary open() is such a handle."""

    def setUp(self):
        self.root = scratch('titan_updater_inuse_')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self._was_frozen = updater_module.is_frozen
        updater_module.is_frozen = lambda: True
        self.addCleanup(lambda: setattr(updater_module, 'is_frozen',
                                        self._was_frozen))
        _log_into(self)

    def _file_in_use_is_replaced(self, archive):
        install = self.install
        notes = os.path.join(install, 'data', 'notes.txt')
        instance = make_updater(install, archive)
        self.addCleanup(instance._release_extractor)
        instance.MOVE_RETRY_WAIT = 0.01

        holder = open(notes, 'rb')          # the running program, reading it
        self.addCleanup(holder.close)
        self.assertTrue(
            instance._extract_archive(archive, Recorder(), 'extracting'),
            instance.failure_reason)

        self.assertEqual(instance.files_in_use, [notes])
        with open(notes, 'rb') as handle:
            self.assertEqual(handle.read(), b'new notes')
        with open(notes + '.old', 'rb') as handle:
            self.assertEqual(handle.read(), b'old notes')
        with open(os.path.join(install, 'Titan.exe'), 'rb') as handle:
            self.assertEqual(handle.read(), b'new titan')
        self.assertIn('notes.txt', instance.failure_message())

    def _install_with_notes(self):
        self.install = build_install(self.root)
        os.makedirs(os.path.join(self.install, 'data'), exist_ok=True)
        with open(os.path.join(self.install, 'data', 'notes.txt'), 'wb') as f:
            f.write(b'old notes')

    @unittest.skipUnless(sys.platform == 'win32', "Windows sharing rules")
    def test_7zip_leaves_a_file_in_use_out_and_it_is_written_over(self):
        """7-Zip deletes before it writes, so the file is excluded from the
        extraction and written over afterwards."""
        self._install_with_notes()
        self._file_in_use_is_replaced(build_arm64_archive(self.root))

    @unittest.skipUnless(sys.platform == 'win32' and HAVE_PY7ZR,
                         "Windows sharing rules, py7zr")
    def test_py7zr_writes_over_a_file_in_use(self):
        self._install_with_notes()
        self._file_in_use_is_replaced(
            build_archive(self.root, extra={'data/notes.txt': b'new notes'}))

    @unittest.skipUnless(sys.platform == 'win32' and HAVE_PY7ZR,
                         "Windows sharing rules, py7zr")
    def test_a_file_in_use_that_would_not_change_is_left_alone(self):
        """The frozen Titan holds _internal/base_library.zip open itself,
        and it is the same bytes in both builds: it must not be written over
        while the process is still reading from it."""
        self._install_with_notes()
        notes = os.path.join(self.install, 'data', 'notes.txt')
        archive = build_archive(self.root, extra={'data/notes.txt': b'old notes'})
        instance = make_updater(self.install, archive)
        self.addCleanup(instance._release_extractor)
        instance.MOVE_RETRY_WAIT = 0.01
        before = os.stat(notes).st_mtime_ns

        holder = open(notes, 'rb')
        self.addCleanup(holder.close)
        self.assertTrue(
            instance._extract_archive(archive, Recorder(), 'extracting'),
            instance.failure_reason)
        self.assertEqual(os.stat(notes).st_mtime_ns, before,
                         "an unchanged file in use was written over")
        with open(os.path.join(self.install, 'Titan.exe'), 'rb') as handle:
            self.assertEqual(handle.read(), b'new titan')

    @unittest.skipUnless(sys.platform == 'win32', "Windows sharing rules")
    def test_rollback_puts_a_copied_file_back(self):
        install = build_install(self.root)
        target = os.path.join(install, 'held.bin')
        with open(target, 'wb') as handle:
            handle.write(b'original')
        instance = make_updater(install, os.path.join(self.root, 'x.7z'))
        instance.MOVE_RETRY_WAIT = 0.01

        holder = open(target, 'rb')
        self.addCleanup(holder.close)
        record = instance._move_aside(target, target + '.old')
        self.assertEqual(record[0], 'copied')
        with open(target, 'wb') as handle:      # what the extractor would do
            handle.write(b'replaced')

        instance._rollback_staging([record])
        with open(target, 'rb') as handle:
            self.assertEqual(handle.read(), b'original')
        self.assertFalse(os.path.exists(target + '.old'))
        self.assertEqual(list(instance.rollback_problems), [])


@unittest.skipUnless(HAVE_7Z, "data/bin/7z.exe is not present")
class WhatWentWrongIsSaid(unittest.TestCase):
    """A compiled Titan has no console; the log and the dialog are all
    there is."""

    def setUp(self):
        self.root = scratch('titan_updater_said_')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.log = _log_into(self)

    def test_the_log_is_written_and_the_dialog_names_the_reason(self):
        install = build_install(self.root)
        instance = make_updater(install, os.path.join(self.root, 'none.7z'))
        self.assertFalse(
            instance._extract_archive(instance.temp_file, Recorder(), 'x'))
        self.assertIn('does not exist', instance.failure_reason)
        message = instance.failure_message()
        self.assertIn(instance.failure_reason, message)
        self.assertIn(self.log, message)
        with open(self.log, encoding='utf-8') as handle:
            self.assertIn('FAILED', handle.read())

    def test_a_local_archive_is_applied_and_left_in_place(self):
        install = build_install(self.root)
        archive = build_archive(self.root, name='given.7z')
        instance = make_updater(install, os.path.join(install, 'titan_update.7z'))
        self.addCleanup(instance._release_extractor)
        self.assertTrue(instance._apply_local_steps(Recorder(), archive))
        with open(os.path.join(install, 'Titan.exe'), 'rb') as handle:
            self.assertEqual(handle.read(), b'new titan')
        self.assertTrue(os.path.exists(archive), "the user's archive was deleted")

    def test_a_missing_local_archive_is_named(self):
        install = build_install(self.root)
        instance = make_updater(install, os.path.join(install, 'titan_update.7z'))
        missing = os.path.join(self.root, 'nowhere.7z')
        self.assertFalse(instance._apply_local_steps(Recorder(), missing))
        self.assertIn('nowhere.7z', instance.failure_reason)


if __name__ == '__main__':
    unittest.main(verbosity=2)
