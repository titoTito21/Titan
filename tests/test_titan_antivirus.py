# -*- coding: utf-8 -*-
"""Titan Antivirus, its shell add-on and its reader module.

Run directly (``tests/`` has no ``__init__.py``). Nothing here opens a
window, speaks, plays a sound or reaches the network: every store points at
a temporary APPDATA, clamd is a stand-in speaking clamd's own protocol on a
local port, and ClamAV is never downloaded.
"""

import importlib.util
import os
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'data', 'applications', 'tAntivirus')
ADDON = os.path.join(ROOT, 'data', 'shell addons', 'titan_antivirus')
sys.path.insert(0, ROOT)
sys.path.insert(0, APP)

_HOME = tempfile.mkdtemp(prefix='tav_home_')
os.environ['APPDATA'] = _HOME
os.environ['HOME'] = _HOME

import av_store                                             # noqa: E402
import av_engine                                            # noqa: E402
import av_quarantine                                        # noqa: E402
import av_guard                                             # noqa: E402
import av_defender                                          # noqa: E402

EVIL = b'TITAN-ANTIVIRUS-TEST-SIGNATURE'


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClamd(object):
    """clamd's protocol, enough of it: PING, SHUTDOWN, IDSESSION with
    INSTREAM and END. A stream containing `EVIL` is a threat."""

    def __init__(self):
        self.server = socket.socket()
        self.server.bind(('127.0.0.1', 0))
        self.server.listen(5)
        self.port = self.server.getsockname()[1]
        self.streams = 0
        self.stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self.stop:
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._talk, args=(connection,),
                             daemon=True).start()

    @staticmethod
    def _command(connection, buffer):
        while b'\0' not in buffer:
            block = connection.recv(4096)
            if not block:
                return None, buffer
            buffer += block
        command, _, rest = buffer.partition(b'\0')
        return command, rest

    @staticmethod
    def _exactly(connection, size, buffer):
        while len(buffer) < size:
            block = connection.recv(65536)
            if not block:
                raise OSError('closed')
            buffer += block
        return buffer[:size], buffer[size:]

    def _talk(self, connection):
        buffer = b''
        counter = 0
        with connection:
            while True:
                command, buffer = self._command(connection, buffer)
                if command is None:
                    return
                if command == b'zPING':
                    connection.sendall(b'PONG\0')
                    return
                if command in (b'zSHUTDOWN', b'zEND'):
                    return
                if command == b'zIDSESSION':
                    continue
                if command == b'zINSTREAM':
                    counter += 1
                    data = b''
                    while True:
                        head, buffer = self._exactly(connection, 4, buffer)
                        size = struct.unpack('>I', head)[0]
                        if not size:
                            break
                        chunk, buffer = self._exactly(connection, size, buffer)
                        data += chunk
                    self.streams += 1
                    verdict = (b'Titan.Test.Signature FOUND' if EVIL in data
                               else b'OK')
                    connection.sendall(b'%d: stream: %s\0' % (counter, verdict))

    def close(self):
        self.stop = True
        self.server.close()


class Fresh(unittest.TestCase):
    """Every test starts with an empty Titan Antivirus folder."""

    def setUp(self):
        shutil.rmtree(av_store.base_folder(), ignore_errors=True)
        self.work = tempfile.mkdtemp(prefix='tav_work_')

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def write(self, name, data):
        path = os.path.normpath(os.path.join(self.work, name))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as handle:
            handle.write(data)
        return path


class TheStoreKeepsWhatItIsGiven(Fresh):
    def test_everything_is_under_titans_user_folder(self):
        self.assertTrue(av_store.base_folder().startswith(_HOME))
        self.assertTrue(av_store.base_folder().endswith('antivirus'))

    def test_settings_answer_defaults_and_keep_changes(self):
        self.assertEqual(av_store.get('threat_action'), 'ask')
        av_store.update(threat_action='quarantine', nonsense=1)
        self.assertEqual(av_store.get('threat_action'), 'quarantine')
        self.assertNotIn('nonsense', av_store.settings())

    def test_a_request_is_written_read_once_and_removed(self):
        path = av_store.write_request(['C:/a', '', 'C:/b'], engine='defender')
        self.assertIn(path, av_store.pending_requests())
        request = av_store.read_request(path)
        self.assertEqual(request['paths'], ['C:/a', 'C:/b'])
        self.assertEqual(request['engine'], 'defender')
        self.assertFalse(os.path.exists(path))
        self.assertIsNone(av_store.read_request(path))

    def test_history_is_bounded(self):
        for index in range(av_store.HISTORY_LIMIT + 5):
            av_store.add_history({'time': index})
        records = av_store.history()
        self.assertEqual(len(records), av_store.HISTORY_LIMIT)
        self.assertEqual(records[0]['time'], av_store.HISTORY_LIMIT + 4)

    def test_one_instance_and_a_dead_pid_is_not_believed(self):
        self.assertTrue(av_store.claim_instance())
        self.assertEqual(av_store.running_instance(), 0)  # it is us
        av_store.release_instance()
        av_store._write_json(av_store._pid_file(), {'pid': 999999999})
        self.assertEqual(av_store.running_instance(), 0)


class ClamdAnswersAreRead(unittest.TestCase):
    def test_replies(self):
        self.assertEqual(av_engine.parse_reply('stream: OK\0'), ('ok', ''))
        self.assertEqual(av_engine.parse_reply('3: stream: Eicar-Sig FOUND'),
                         ('found', 'Eicar-Sig'))
        self.assertEqual(av_engine.parse_reply(
            'INSTREAM size limit exceeded. ERROR')[0], 'error')
        self.assertEqual(av_engine.parse_reply('')[0], 'error')

    def test_the_newest_stable_windows_zip_is_picked(self):
        releases = [
            {'prerelease': True, 'assets': [
                {'name': 'clamav-1.6.0-rc.win.x64.zip',
                 'browser_download_url': 'rc'}]},
            {'prerelease': False, 'assets': [
                {'name': 'clamav-1.5.1.linux.x86_64.deb',
                 'browser_download_url': 'deb'},
                {'name': 'clamav-1.5.1.win.x64.zip',
                 'browser_download_url': 'zip', 'digest': 'sha256:ab12'}]},
        ]
        self.assertEqual(av_engine.pick_windows_asset(releases),
                         ('clamav-1.5.1.win.x64.zip', 'zip', 'ab12'))
        self.assertIsNone(av_engine.pick_windows_asset([]))

    def test_configs_point_at_our_folders(self):
        av_engine.write_configs()
        with open(os.path.join(av_store.base_folder(), 'clamd.conf'),
                  encoding='utf-8') as handle:
            text = handle.read()
        self.assertIn(av_engine.database_folder(), text)
        self.assertIn('TCPAddr 127.0.0.1', text)
        self.assertNotIn('Example', text)


class AScanFindsWhatIsThere(Fresh):
    def setUp(self):
        super().setUp()
        self.clamd_server = FakeClamd()
        av_store.update(clamd_port=self.clamd_server.port, use_clamd=True)
        self.saved = (av_engine.installed, av_engine.has_databases,
                      av_engine.locate)
        av_engine.installed = lambda: True
        av_engine.has_databases = lambda: True
        av_engine.locate = lambda: {'clamscan': 'x', 'clamd': 'x',
                                    'freshclam': 'x'}

    def tearDown(self):
        (av_engine.installed, av_engine.has_databases,
         av_engine.locate) = self.saved
        self.clamd_server.close()
        super().tearDown()

    def run_job(self, paths, **extra):
        found, progress, done = [], [], []
        job = av_engine.ScanJob(
            paths, clamd=av_engine.Clamd(), label='test',
            on_found=found.append,
            on_progress=lambda d, t, p: progress.append((d, t)),
            on_done=done.append, **extra)
        job.run()
        return job, found, progress, done[0]

    def test_a_threat_is_found_and_a_clean_file_is_not(self):
        clean = self.write('docs/clean.txt', b'hello')
        bad = self.write('docs/zażółć.exe', b'MZ' + EVIL + b'tail')
        self.write('docs/empty.bin', b'')
        job, found, progress, summary = self.run_job([self.work])
        self.assertEqual([one.path for one in found], [bad])
        self.assertEqual(found[0].threat, 'Titan.Test.Signature')
        self.assertEqual(summary['threats'], 1)
        self.assertEqual(summary['files'], 3)
        self.assertEqual(progress[-1], (3, 3))
        self.assertNotIn(clean, [one.path for one in found])
        record = av_store.history()[0]
        self.assertEqual(record['findings'][0]['path'], bad)

    def test_a_file_over_the_limit_is_skipped_not_scanned(self):
        av_store.update(max_file_mb=1)
        self.write('big.bin', EVIL + b'x' * (2 << 20))
        job, found, progress, summary = self.run_job([self.work])
        self.assertEqual(found, [])
        self.assertEqual(summary['skipped'], 1)

    def test_exclusions_and_the_quarantine_folder_are_not_scanned(self):
        bad = self.write('skip/bad.exe', EVIL)
        av_store.update(exclusions=[os.path.dirname(bad)])
        stored = os.path.join(av_store.folder('quarantine'), 'x.qar')
        with open(stored, 'wb') as handle:
            handle.write(EVIL)
        job, found, progress, summary = self.run_job(
            [self.work, av_store.folder('quarantine')])
        self.assertEqual(found, [])

    def test_cancelling_stops_the_scan(self):
        for index in range(30):
            self.write(f'f{index}.txt', b'data')
        job = av_engine.ScanJob([self.work], clamd=av_engine.Clamd())
        job.on_progress = lambda d, t, p: job.cancel()
        summaries = []
        job.on_done = summaries.append
        job.run()
        self.assertTrue(summaries[0]['cancelled'])
        self.assertLess(summaries[0]['files'], 30)


class QuarantineGivesTheSameBytesBack(Fresh):
    def test_round_trip(self):
        data = os.urandom(200000) + EVIL
        path = self.write('evil.exe', data)
        record = av_quarantine.put(path, 'Titan.Test', 'clamav')
        self.assertFalse(os.path.exists(path))
        stored = os.path.join(av_store.folder('quarantine'),
                              record['id'] + '.qar')
        with open(stored, 'rb') as handle:
            self.assertNotIn(EVIL, handle.read())
        self.assertEqual([one['id'] for one in av_quarantine.items()],
                         [record['id']])
        restored = av_quarantine.restore(record['id'])
        with open(restored, 'rb') as handle:
            self.assertEqual(handle.read(), data)
        self.assertEqual(av_quarantine.items(), [])

    def test_restoring_never_overwrites(self):
        path = self.write('a.exe', EVIL)
        record = av_quarantine.put(path)
        self.write('a.exe', b'new file')
        restored = av_quarantine.restore(record['id'])
        self.assertNotEqual(os.path.normcase(restored), os.path.normcase(path))
        with open(path, 'rb') as handle:
            self.assertEqual(handle.read(), b'new file')

    def test_a_damaged_copy_is_refused(self):
        record = av_quarantine.put(self.write('b.exe', EVIL + b'123'))
        stored = os.path.join(av_store.folder('quarantine'),
                              record['id'] + '.qar')
        with open(stored, 'r+b') as handle:
            handle.write(b'\0\0\0')
        with self.assertRaises(ValueError):
            av_quarantine.restore(record['id'])


class TheGuardWatchesAndSchedules(Fresh):
    def test_a_finished_download_is_handed_over_once(self):
        seen = []
        self.write('old.txt', b'old')
        watch = av_guard.DownloadsWatch(seen.append, folder=self.work)
        watch.prime()
        self.write('file.crdownload', b'partial')
        new = self.write('setup.exe', b'data')
        watch.folder_mtime = None                  # the folder changed
        self.assertEqual(watch.tick(), [])          # still maybe growing
        self.assertEqual(watch.tick(), [new])       # the same size: done
        self.assertEqual(watch.tick(), [])          # never twice
        self.assertEqual(seen, [new])

    def test_the_schedule_runs_once_a_day_after_its_time(self):
        settings = {'schedule_enabled': True, 'schedule_time': '12:00',
                    'schedule_last_day': ''}
        morning = time.strptime('2026-10-10 09:00', '%Y-%m-%d %H:%M')
        noon = time.strptime('2026-10-10 12:01', '%Y-%m-%d %H:%M')
        self.assertFalse(av_guard.due_today(settings, morning))
        self.assertTrue(av_guard.due_today(settings, noon))
        settings['schedule_last_day'] = '2026-10-10'
        self.assertFalse(av_guard.due_today(settings, noon))
        settings['schedule_enabled'] = False
        settings['schedule_last_day'] = ''
        self.assertFalse(av_guard.due_today(settings, noon))


class DefendersOutputIsRead(unittest.TestCase):
    def test_threats_and_their_files(self):
        output = """Scan starting...
Scan finished.
Scanning C:\\Users\\x\\Downloads found 1 threats.
<===========================LIST OF DETECTED THREATS==========================>
----------------------------- Threat information ------------------------------
Threat                  : Virus:DOS/EICAR_Test_File
Resources               : 1 total
    file                : C:\\Users\\x\\Downloads\\eicar.com
-------------------------------------------------------------------------------
"""
        self.assertEqual(av_defender.parse_output(output),
                         [('C:\\Users\\x\\Downloads\\eicar.com',
                           'Virus:DOS/EICAR_Test_File')])
        self.assertEqual(av_defender.parse_output('Threat : X', 'C:/a'),
                         [('C:/a', 'X')])
        self.assertEqual(av_defender.parse_output('no threats'), [])


class TheShellAddonHandsTheScanOver(Fresh):
    def setUp(self):
        super().setUp()
        self.addon = _load(os.path.join(ADDON, 'init.py'), 'tav_addon_test')
        self.addon._cache.clear()
        self.addon._cache['store'] = av_store
        self.addon._cache['gettext'] = lambda text: text
        self.launched = []
        self.addon._app_info = lambda: {'path': APP, 'shortname': 'tantivirus'}
        from src.titan_core import app_manager
        self.saved_open = app_manager.open_application
        app_manager.open_application = lambda info, argument=None: \
            self.launched.append(argument)

        class Api(object):
            spoken = []

            def speak(self, text, interrupt=True):
                self.spoken.append(text)

            def log(self, text):
                pass
        self.api = Api()

    def tearDown(self):
        from src.titan_core import app_manager
        app_manager.open_application = self.saved_open
        super().tearDown()

    def test_a_files_menu_carries_the_branch(self):
        entries = self.addon.explorer_context_items(
            self.api, None, 'item', [{'path': 'C:/x/a.exe'}, {'root': 'D:\\'}])
        self.assertEqual(len(entries), 1)
        branch = entries[0]
        self.assertEqual(branch['label'], 'Scan with antivirus:')
        labels = [child['label'] for child in branch['children']]
        self.assertEqual(labels[0], 'Titan Antivirus')
        if self.addon.defender_available():
            self.assertIn('Microsoft Defender', labels)
        branch['children'][0]['action']()
        self.assertEqual(len(self.launched), 1)
        request = av_store.read_request(self.launched[0])
        self.assertEqual(request['paths'], ['C:/x/a.exe', 'D:\\'])
        self.assertEqual(request['engine'], 'clamav')

    def test_nothing_selected_is_no_entry(self):
        self.assertEqual(self.addon.explorer_context_items(
            self.api, None, 'item', []), [])
        self.assertEqual(self.addon.desktop_menu_items(
            self.api, None, 'background', None), [])

    def test_a_running_instance_is_not_started_again(self):
        self.addon._store = lambda: _Running(av_store)
        self.addon.send(self.api, 'scan', ['C:/a'])
        self.assertEqual(self.launched, [])
        self.assertEqual(len(av_store.pending_requests()), 1)

    def test_the_guard_starts_with_the_shell_only_when_wanted(self):
        self.addon.on_shell_start(self.api, None)
        self.assertEqual(self.launched, [])
        av_store.update(watch_downloads=True)
        self.addon.on_shell_start(self.api, None)
        self.assertEqual(self.launched, ['--guard'])

    def test_every_hook_is_one_titan_calls_with_its_arguments(self):
        from src.shell import addons
        import inspect
        for name, value in vars(self.addon).items():
            if name in addons.ALL_HOOKS:
                arity = len(inspect.signature(value).parameters)
                self.assertEqual(arity, addons.HOOK_ARGS[name], name)

    def test_the_creation_kit_check_accepts_it(self):
        try:
            from src.ai import ai_creation_kit
        except Exception as error:                  # noqa: BLE001
            self.skipTest(f'creation kit not importable: {error}')
        files = {}
        for name in ('init.py', '__shell_addon__.TCE'):
            with open(os.path.join(ADDON, name), encoding='utf-8') as handle:
                files[name] = handle.read()
        problems = ai_creation_kit.check_shell_addon(files)
        self.assertEqual(problems, [], problems)


class _Running(object):
    def __init__(self, store):
        self.store = store

    def __getattr__(self, name):
        return getattr(self.store, name)

    def running_instance(self):
        return 4242


class TheShellPutsABranchInASubmenu(unittest.TestCase):
    def test_children_become_a_submenu(self):
        try:
            import wx
        except ImportError:
            self.skipTest('no wxPython')
        app = wx.App(False)
        from src.shell import addons
        called = []
        menu = wx.Menu()
        added = addons.add_to_menu(menu, [
            {'id': 'b', 'addon': 'x', 'label': 'Scan with antivirus:',
             'children': [{'id': 'c', 'label': 'Titan Antivirus',
                           'action': lambda: called.append(1)}]},
            {'id': 'empty', 'addon': 'x', 'label': 'Nothing', 'children': []},
        ])
        self.assertEqual(added, 1)
        item = menu.FindItemByPosition(0)
        self.assertTrue(item.IsSubMenu())
        self.assertEqual(item.GetSubMenu().GetMenuItemCount(), 1)
        menu.Destroy()
        app.Destroy()


class TheReaderModuleIsValidAndShared(unittest.TestCase):
    def test_schema_and_both_trees(self):
        shipped = os.path.join(ROOT, 'nvda-addon', 'addon', 'globalPlugins',
                               'titanEnhancements', 'readerModules')
        vendored = os.path.join(ROOT, 'data', 'components', 'titan access',
                                'titan_access', 'portable', 'readerModules')
        schema = _load(os.path.join(shipped, 'schema.py'), 'tav_schema')
        module = _load(os.path.join(shipped, 'tantivirus.py'), 'tav_module')
        self.assertEqual(schema.problems(module.MODULE), [])
        with open(os.path.join(shipped, 'tantivirus.py'), 'rb') as one, \
                open(os.path.join(vendored, 'tantivirus.py'), 'rb') as two:
            self.assertEqual(one.read(), two.read())
        # The Threat column the module names is the column the window has,
        # in both of the window's languages.
        with open(os.path.join(APP, 'main.py'), encoding='utf-8') as handle:
            self.assertIn('(_("Threat"), 240)', handle.read())
        with open(os.path.join(APP, 'languages', 'pl', 'LC_MESSAGES',
                               'messages.po'), encoding='utf-8') as handle:
            self.assertIn('msgstr "Zagrożenie"', handle.read())


class TheWindowShowsFindings(Fresh):
    """The real frame, built and never shown."""

    def test_a_finding_becomes_a_row_and_an_action_changes_it(self):
        try:
            import wx
        except ImportError:
            self.skipTest('no wxPython')
        app = wx.App(False)
        main = _load(os.path.join(APP, 'main.py'), 'tav_main_test')
        main.speak = lambda text: None
        main.play = lambda name: None

        class FakeApp(object):
            clamd = av_engine.Clamd()
            guard = av_guard.Guard(lambda p: None, lambda s: None)

            def apply_settings(self):
                pass
        frame = main.MainFrame(FakeApp())
        try:
            bad = self.write('bad.exe', EVIL)
            av_store.update(threat_action='report')
            finding = av_engine.Finding(bad, 'Titan.Test')
            frame._on_found(finding)
            self.assertEqual(frame.results.GetItemCount(), 1)
            self.assertEqual(frame.results.GetItemText(0, 1), 'Titan.Test')
            frame.results.Select(0)
            frame._act_selected('quarantine')
            self.assertEqual(finding.status, 'quarantined')
            self.assertFalse(os.path.exists(bad))
            self.assertEqual(frame.results.GetItemText(0, 2),
                             main.STATUS_WORDS['quarantined']())
            self.assertEqual(frame.gauge.GetName(), main._("Scan progress"))
            frame._on_done({'files': 1, 'threats': 1, 'errors': 0,
                            'skipped': 0, 'cancelled': False, 'error': ''})
            self.assertIn('1', frame.status.GetStatusText())
        finally:
            frame.Destroy()
            app.Destroy()


if __name__ == '__main__':
    try:
        unittest.main(verbosity=1)
    finally:
        shutil.rmtree(_HOME, ignore_errors=True)
