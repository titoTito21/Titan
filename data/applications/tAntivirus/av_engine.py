# -*- coding: utf-8 -*-
"""The ClamAV engine, as Titan Antivirus drives it.

Three ClamAV programs are used and nothing else of it:

* **freshclam** keeps the signature databases current;
* **clamd** loads them once and answers scans over a socket - the reason a
  second scan from the shell's menu takes a moment instead of the twenty to
  forty seconds every ``clamscan`` spends loading a few hundred megabytes of
  signatures;
* **clamscan** is the floor, for a machine where clamd will not start.

Where ClamAV comes from: on Windows the official portable build is
downloaded once into Titan's own user folder (``antivirus/engine``) - the
release Cisco Talos publishes on GitHub, checked against the SHA-256 GitHub
records for it - so Titan's own download does not grow by the engine and
nothing is installed system-wide. A ClamAV the user already has (Program
Files, or on PATH) is used instead when there is one, and on Linux and
macOS the system's own ``clamscan``/``clamd``/``freshclam`` are what is
used.

**A file is scanned by streaming its bytes to clamd (INSTREAM), never by
naming its path.** clamd reads a path with its own idea of the file
system's encoding, which on Windows is not Python's, and a file name with a
Polish letter in it would be "not found" rather than scanned. Streaming
also means a file the user can read is a file clamd can scan.

Nothing here imports wx or Titan: the window, the guard and the tests all
drive the same `Engine`.
"""

import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

import av_store

RELEASES_API = 'https://api.github.com/repos/Cisco-Talos/clamav/releases'
USER_AGENT = 'TitanAntivirus/1.0 (+Titan TCE)'
#: clamd's own default for one streamed file is 25 MB; ours follows the
#: user's "largest file to scan" setting instead.
CHUNK = 64 * 1024
IS_WINDOWS = sys.platform == 'win32'
EXE = '.exe' if IS_WINDOWS else ''
PROGRAMS = ('clamscan', 'clamd', 'freshclam')


class EngineError(Exception):
    """Something the user should be told in one sentence."""


class Finding(object):
    """One threat: which file, what it is, and which engine said so."""

    __slots__ = ('path', 'threat', 'engine', 'status')

    def __init__(self, path, threat, engine='clamav', status='found'):
        self.path = path
        self.threat = threat
        self.engine = engine
        self.status = status

    def as_dict(self):
        return {'path': self.path, 'threat': self.threat,
                'engine': self.engine, 'status': self.status}

    def __repr__(self):
        return f'Finding({self.path!r}, {self.threat!r})'


def _no_window():
    """Keyword arguments that keep a console program's window off the
    screen - a black box flashing up is noise to somebody who cannot see it
    and a focus change their screen reader announces."""
    if not IS_WINDOWS:
        return {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return {'startupinfo': info,
            'creationflags': subprocess.CREATE_NO_WINDOW}


# --------------------------------------------------------------------------
# Finding ClamAV
# --------------------------------------------------------------------------
def _program_in(folder, name):
    """``name`` in ``folder`` or one level down (the portable zip unpacks
    into a folder named after its version)."""
    if not folder or not os.path.isdir(folder):
        return ''
    direct = os.path.join(folder, name + EXE)
    if os.path.isfile(direct):
        return direct
    try:
        children = sorted(os.listdir(folder), reverse=True)
    except OSError:
        return ''
    for child in children:
        candidate = os.path.join(folder, child, name + EXE)
        if os.path.isfile(candidate):
            return candidate
    return ''


def candidate_folders():
    folders = [av_store.folder('engine')]
    if IS_WINDOWS:
        for variable in ('ProgramFiles', 'ProgramFiles(x86)'):
            root = os.environ.get(variable)
            if root:
                folders.append(os.path.join(root, 'ClamAV'))
    return folders


def locate():
    """``{'clamscan': path, 'clamd': path, 'freshclam': path}``, with ''
    for what is not on this machine. Titan's own copy first, then an
    installed one, then PATH."""
    found = {name: '' for name in PROGRAMS}
    for folder in candidate_folders():
        clamscan = _program_in(folder, 'clamscan')
        if not clamscan:
            continue
        home = os.path.dirname(clamscan)
        for name in PROGRAMS:
            path = os.path.join(home, name + EXE)
            if os.path.isfile(path):
                found[name] = path
        break
    for name in PROGRAMS:
        if not found[name]:
            found[name] = shutil.which(name) or ''
            if not found[name] and not IS_WINDOWS:
                # clamd lives in sbin on most distributions, which is not
                # on an ordinary user's PATH.
                for root in ('/usr/sbin', '/usr/local/sbin', '/sbin'):
                    path = os.path.join(root, name)
                    if os.path.isfile(path):
                        found[name] = path
                        break
    return found


def installed():
    return bool(locate()['clamscan'])


#: Where a Linux or macOS distribution's own freshclam service keeps the
#: signatures. It runs as root and keeps them current by itself, and a
#: user can read them - so where it exists, nothing needs downloading.
SYSTEM_DATABASE_FOLDERS = () if IS_WINDOWS else (
    '/var/lib/clamav', '/usr/local/share/clamav', '/var/db/clamav',
    '/opt/homebrew/var/lib/clamav', '/usr/local/var/lib/clamav')


def _complete(folder):
    """True when ``folder`` holds a main database and a daily one, in
    either of their two forms."""
    try:
        names = os.listdir(folder)
    except OSError:
        return False
    stems = {os.path.splitext(name)[0] for name in names
             if name.endswith(('.cvd', '.cld'))}
    return 'main' in stems and 'daily' in stems


def own_database_folder():
    return av_store.folder('db')


def system_database_folder():
    """The distribution's own signatures, when they are complete; ''."""
    for folder in SYSTEM_DATABASE_FOLDERS:
        if _complete(folder):
            return folder
    return ''


def database_folder():
    """Where the signatures a scan uses are: our own when we have them,
    otherwise the system's (Linux, macOS), otherwise our own folder for
    freshclam to fill."""
    own = own_database_folder()
    if _complete(own):
        return own
    return system_database_folder() or own


def uses_system_databases():
    return database_folder() != own_database_folder()


def has_databases():
    """True when the signatures are there to scan with."""
    return _complete(database_folder())


def database_age_days():
    """How old the newest signature file is, in days; None with none."""
    newest = 0
    folder = database_folder()
    try:
        for name in os.listdir(folder):
            if name.endswith(('.cvd', '.cld')):
                newest = max(newest, os.path.getmtime(
                    os.path.join(folder, name)))
    except OSError:
        return None
    if not newest:
        return None
    return max(0.0, (time.time() - newest) / 86400.0)


# --------------------------------------------------------------------------
# Downloading ClamAV (Windows)
# --------------------------------------------------------------------------
def _get_json(url):
    request = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT, 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode('utf-8'))


def pick_windows_asset(releases):
    """The portable 64-bit zip of the newest stable release, as
    ``(name, url, sha256_or_empty)``; None when there is none.

    Releases are walked newest first and a pre-release is passed over -
    an antivirus is the last program to run a release candidate of.
    """
    for release in releases or []:
        if not isinstance(release, dict):
            continue
        if release.get('prerelease') or release.get('draft'):
            continue
        for asset in release.get('assets') or []:
            name = str(asset.get('name') or '')
            if name.endswith('.win.x64.zip') and name.startswith('clamav-'):
                digest = str(asset.get('digest') or '')
                sha = digest[7:] if digest.startswith('sha256:') else ''
                return name, asset.get('browser_download_url'), sha
    return None


def download_engine(progress=None, cancel=None):
    """Download and unpack the portable ClamAV into ``antivirus/engine``.

    ``progress(done_bytes, total_bytes)`` is called as it arrives;
    ``cancel()`` answering True stops it. Raises `EngineError` with a
    sentence for the user.
    """
    if not IS_WINDOWS:
        raise EngineError('install_with_system')
    try:
        releases = _get_json(RELEASES_API + '?per_page=10')
    except Exception as error:                      # noqa: BLE001
        raise EngineError(f'release_list:{error}')
    picked = pick_windows_asset(releases)
    if not picked:
        raise EngineError('no_windows_build')
    name, url, expected = picked
    target = av_store.folder('engine')
    archive = os.path.join(target, name + '.part')
    digest = hashlib.sha256()
    try:
        request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response, \
                open(archive, 'wb') as handle:
            total = int(response.headers.get('Content-Length') or 0)
            done = 0
            while True:
                if cancel and cancel():
                    raise EngineError('cancelled')
                block = response.read(CHUNK)
                if not block:
                    break
                handle.write(block)
                digest.update(block)
                done += len(block)
                if progress:
                    progress(done, total)
    except EngineError:
        _remove(archive)
        raise
    except Exception as error:                      # noqa: BLE001
        _remove(archive)
        raise EngineError(f'download:{error}')
    if expected and digest.hexdigest().lower() != expected.lower():
        _remove(archive)
        raise EngineError('checksum')
    try:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                # A name that climbs out of the folder is not written.
                resolved = os.path.realpath(os.path.join(target, member))
                if not resolved.startswith(os.path.realpath(target)):
                    raise EngineError('archive')
            bundle.extractall(target)
    except zipfile.BadZipFile:
        raise EngineError('archive')
    finally:
        _remove(archive)
    if not installed():
        raise EngineError('archive')
    return locate()


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


# --------------------------------------------------------------------------
# Configuration files
# --------------------------------------------------------------------------
def _conf_path(name):
    return os.path.join(av_store.base_folder(), name)


def certs_folder():
    """ClamAV 1.5's signature-verification certificates, when they are
    beside the programs rather than where ClamAV was built to look (a
    portable or unpacked copy); '' when the default is right.

    Written into the configuration only when found, because an older
    ClamAV does not know the option and refuses the whole file over it.
    """
    program = locate()['freshclam'] or locate()['clamd']
    if not program:
        return ''
    home = os.path.dirname(program)
    for candidate in (os.path.join(home, 'certs'),
                      os.path.join(home, '..', 'etc', 'certs'),
                      os.path.join(home, '..', 'etc', 'clamav', 'certs')):
        if os.path.isdir(candidate):
            return os.path.normpath(candidate)
    return ''


def write_configs():
    """freshclam.conf and clamd.conf of our own, in Titan's folder.

    ClamAV refuses to run with its shipped example files (they carry an
    ``Example`` line on purpose), and the system's own would put the
    databases somewhere a user cannot write. Rewritten on every start so a
    changed setting is in force.
    """
    settings = av_store.settings()
    own = own_database_folder()
    db = database_folder()
    max_mb = max(1, int(settings.get('max_file_mb') or 200))
    freshclam = [
        f'DatabaseDirectory {own}',
        'DatabaseMirror database.clamav.net',
        f'UpdateLogFile {_conf_path("freshclam.log")}',
        'LogFileMaxSize 2M',
        'Checks 0',
        'ConnectTimeout 30',
        'ReceiveTimeout 60',
    ]
    clamd = [
        f'DatabaseDirectory {db}',
        'TCPAddr 127.0.0.1',
        f'TCPSocket {int(settings.get("clamd_port") or 33310)}',
        'Foreground yes',
        f'LogFile {_conf_path("clamd.log")}',
        'LogFileMaxSize 2M',
        f'StreamMaxLength {max_mb}M',
        f'MaxFileSize {max_mb}M',
        f'MaxScanSize {max_mb * 2}M',
        'MaxThreads 4',
        'IdleTimeout 600',
        f'ScanArchive {"yes" if settings.get("scan_archives") else "no"}',
    ]
    certs = certs_folder()
    if certs:
        freshclam.append(f'CVDCertsDirectory {certs}')
        clamd.append(f'CVDCertsDirectory {certs}')
    if not IS_WINDOWS:
        clamd.append(f'PidFile {_conf_path("clamd.pid")}')
        freshclam.append(f'PidFile {_conf_path("freshclam.pid")}')
    for name, lines in (('freshclam.conf', freshclam), ('clamd.conf', clamd)):
        with open(_conf_path(name), 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(lines) + '\n')


# --------------------------------------------------------------------------
# Updating the signatures
# --------------------------------------------------------------------------
def update_databases(on_line=None, cancel=None):
    """Run freshclam; answer True when the databases are there afterwards.

    ``on_line(text)`` hears freshclam's own lines as they come, which is the
    only progress a three-hundred-megabyte first download has.
    """
    programs = locate()
    if uses_system_databases():
        # The distribution's freshclam service keeps these current, as
        # root; ours would only download a second copy - and an old
        # distribution's freshclam is refused by the update server anyway.
        if on_line:
            on_line(f'Using the system signatures in {database_folder()}, '
                    'kept current by the system\'s freshclam service.')
        return True
    if not programs['freshclam']:
        raise EngineError('not_installed')
    write_configs()
    command = [programs['freshclam'],
               f'--config-file={_conf_path("freshclam.conf")}', '--stdout']
    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT,
                               cwd=os.path.dirname(programs['freshclam']),
                               **_no_window())
    last = ''
    refused = ''
    try:
        for raw in iter(process.stdout.readline, b''):
            if cancel and cancel():
                process.kill()
                raise EngineError('cancelled')
            line = raw.decode('utf-8', 'replace').strip()
            if line:
                last = line
                lowered = line.lower()
                # The update server turns away versions past their end of
                # life (an old distribution's ClamAV), and after a refusal
                # freshclam will not ask again until a cool-down ends.
                if 'blocked by cdn' in lowered or 'cool-down' in lowered \
                        or 'outdated' in lowered and 'version' in lowered:
                    refused = refused or line
                if on_line:
                    on_line(line)
        process.wait(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
    if refused and process.returncode:
        raise EngineError('refused:' + refused)
    if has_databases():
        av_store.update(last_update=time.time())
        return True
    # What freshclam said last is the reason, and is kept for the log.
    raise EngineError('update_failed:' + last)


# --------------------------------------------------------------------------
# clamd: the daemon and the conversation with it
# --------------------------------------------------------------------------
def parse_reply(reply):
    """``(status, threat)`` out of one clamd answer.

    ``stream: OK`` is clean, ``stream: Win.Test.EICAR_HDB-1 FOUND`` is a
    threat, anything ending ``ERROR`` (a file over the size limit, a
    corrupt archive) is an error and never a threat. A session answer is
    prefixed with its request number (``3: stream: OK``), which is taken
    off first.
    """
    text = (reply or '').strip().strip('\0').strip()
    if not text:
        return 'error', ''
    head, _, rest = text.partition(': ')
    if head.isdigit() and rest:
        text = rest
    if text.endswith(' FOUND'):
        body = text[:-len(' FOUND')]
        _, _, threat = body.rpartition(': ')
        return 'found', (threat or body).strip()
    if text.endswith(' OK') or text == 'OK':
        return 'ok', ''
    return 'error', text


class Clamd(object):
    """One clamd, started by us and stopped by us.

    Started on the first scan and stopped after ``clamd_idle_minutes`` of
    nothing - it holds the whole signature set in memory (around a
    gigabyte), and a user who scanned one download an hour ago should not
    be paying that for the rest of the day.
    """

    def __init__(self):
        self.process = None
        self.last_used = 0.0
        self._lock = threading.RLock()
        self._watch = None

    @property
    def port(self):
        return int(av_store.get('clamd_port') or 33310)

    def _connect(self, timeout=5.0):
        return socket.create_connection(('127.0.0.1', self.port),
                                        timeout=timeout)

    def ping(self):
        try:
            with self._connect(timeout=1.0) as connection:
                connection.sendall(b'zPING\0')
                return connection.recv(64).strip(b'\0').strip() == b'PONG'
        except OSError:
            return False

    def running(self):
        return self.ping()

    def start(self, wait=180.0, cancel=None):
        """Start clamd (or find one already answering on our port) and wait
        until it answers. Loading the signatures is most of a minute on a
        slow disk, so the wait is long and can be cancelled."""
        with self._lock:
            if self.ping():
                self.last_used = time.time()
                return True
            programs = locate()
            if not programs['clamd']:
                raise EngineError('not_installed')
            if not has_databases():
                raise EngineError('no_databases')
            write_configs()
            self.process = subprocess.Popen(
                [programs['clamd'], f'--config-file={_conf_path("clamd.conf")}'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                cwd=os.path.dirname(programs['clamd']), **_no_window())
        deadline = time.time() + wait
        while time.time() < deadline:
            if cancel and cancel():
                raise EngineError('cancelled')
            if self.process.poll() is not None:
                raise EngineError('clamd_died')
            if self.ping():
                self.last_used = time.time()
                self._start_idle_watch()
                return True
            time.sleep(0.5)
        self.stop()
        raise EngineError('clamd_timeout')

    def _start_idle_watch(self):
        if self._watch and self._watch.is_alive():
            return
        self._watch = threading.Thread(target=self._idle_loop, daemon=True,
                                       name='TitanAntivirusClamdIdle')
        self._watch.start()

    def _idle_loop(self):
        while self.process is not None and self.process.poll() is None:
            time.sleep(15)
            minutes = int(av_store.get('clamd_idle_minutes') or 0)
            if minutes and time.time() - self.last_used > minutes * 60:
                self.stop()
                return

    def stop(self):
        """Ask clamd to shut down; kill it if it will not."""
        with self._lock:
            process, self.process = self.process, None
        if process is None:
            return
        try:
            with self._connect(timeout=2.0) as connection:
                connection.sendall(b'zSHUTDOWN\0')
        except OSError:
            pass
        try:
            process.wait(timeout=10)
        except Exception:                           # noqa: BLE001
            process.kill()

    def session(self):
        self.last_used = time.time()
        return ClamdSession(self._connect(timeout=30.0))


class ClamdSession(object):
    """One IDSESSION: many files over one connection, answered in order."""

    def __init__(self, connection):
        self.connection = connection
        self.counter = 0
        self.buffer = b''
        connection.sendall(b'zIDSESSION\0')

    def _reply(self):
        while b'\0' not in self.buffer:
            block = self.connection.recv(4096)
            if not block:
                raise EngineError('clamd_closed')
            self.buffer += block
        reply, _, self.buffer = self.buffer.partition(b'\0')
        return reply.decode('utf-8', 'replace')

    def scan_stream(self, handle):
        """Stream an open file; answer ``(status, threat)``."""
        self.counter += 1
        self.connection.sendall(b'zINSTREAM\0')
        while True:
            block = handle.read(CHUNK)
            if not block:
                break
            self.connection.sendall(struct.pack('>I', len(block)) + block)
        self.connection.sendall(struct.pack('>I', 0))
        return parse_reply(self._reply())

    def close(self):
        try:
            self.connection.sendall(b'zEND\0')
        except OSError:
            pass
        try:
            self.connection.close()
        except OSError:
            pass


# --------------------------------------------------------------------------
# Which files a scan covers
# --------------------------------------------------------------------------
def quick_scan_folders():
    """Where something a user brought onto the machine usually lands."""
    import av_guard
    home = os.path.expanduser('~')
    folders = [av_guard.downloads_folder()]
    for kind, name in (('DESKTOP', 'Desktop'), ('DOCUMENTS', 'Documents')):
        folders.append(av_guard.xdg_folder(kind) or os.path.join(home, name))
    temporary = os.environ.get('TEMP') or os.environ.get('TMPDIR') or '/tmp'
    folders.append(temporary)
    if IS_WINDOWS:
        startup = os.path.join(os.environ.get('APPDATA', ''), 'Microsoft',
                               'Windows', 'Start Menu', 'Programs', 'Startup')
        folders.append(startup)
    return [folder for folder in folders if os.path.isdir(folder)]


def full_scan_folders():
    """Every fixed drive (Windows) or the home folder (elsewhere)."""
    if not IS_WINDOWS:
        return [os.path.expanduser('~')]
    import ctypes
    drives = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for index in range(26):
        if bitmask & (1 << index):
            root = f'{chr(65 + index)}:\\'
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:   # FIXED
                drives.append(root)
    return drives


def _excluded(path, exclusions):
    lowered = os.path.normcase(os.path.abspath(path))
    for exclusion in exclusions:
        if not exclusion:
            continue
        rule = os.path.normcase(os.path.abspath(exclusion))
        if lowered == rule or lowered.startswith(rule.rstrip('\\/') + os.sep):
            return True
    return False


def iter_files(paths, exclusions=(), cancel=None):
    """Every regular file under ``paths``, skipping exclusions, links and
    Titan's own quarantine (a quarantined file IS a threat, on purpose)."""
    skip = list(exclusions) + [av_store.folder('quarantine'),
                               av_store.folder('engine'), database_folder()]
    seen = set()
    for root in paths:
        if cancel and cancel():
            return
        if not root:
            continue
        if os.path.isfile(root):
            if not _excluded(root, skip) and root not in seen:
                seen.add(root)
                yield root
            continue
        for folder, folders, files in os.walk(root, onerror=lambda e: None):
            if cancel and cancel():
                return
            if _excluded(folder, skip):
                folders[:] = []
                continue
            folders[:] = [name for name in folders
                          if not os.path.islink(os.path.join(folder, name))]
            for name in files:
                path = os.path.join(folder, name)
                if path in seen or os.path.islink(path):
                    continue
                seen.add(path)
                yield path


# --------------------------------------------------------------------------
# A scan
# --------------------------------------------------------------------------
class ScanJob(object):
    """One scan of some paths, run on a thread of its own.

    Callbacks (all from the scan's thread - a window marshals them):

    * ``on_status(key, **values)`` - what it is doing ("counting",
      "starting_engine", "scanning");
    * ``on_progress(done, total, path)`` - after every file;
    * ``on_found(finding)`` - the moment a threat is found, not at the end;
    * ``on_done(summary)`` - once, with ``{'files', 'threats', 'errors',
      'skipped', 'seconds', 'cancelled', 'error'}``.
    """

    def __init__(self, paths, engine=None, label='', on_status=None,
                 on_progress=None, on_found=None, on_done=None, clamd=None):
        self.paths = [str(one) for one in paths if one]
        self.engine = engine or 'clamav'
        self.label = label
        self.on_status = on_status or (lambda key, **values: None)
        self.on_progress = on_progress or (lambda done, total, path: None)
        self.on_found = on_found or (lambda finding: None)
        self.on_done = on_done or (lambda summary: None)
        self.clamd = clamd
        self.findings = []
        self.cancelled = False
        self.thread = None

    def cancel(self):
        self.cancelled = True

    def is_cancelled(self):
        return self.cancelled

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True,
                                       name='TitanAntivirusScan')
        self.thread.start()
        return self

    def run(self):
        started = time.time()
        summary = {'files': 0, 'threats': 0, 'errors': 0, 'skipped': 0,
                   'cancelled': False, 'error': '', 'engine': self.engine}
        try:
            settings = av_store.settings()
            self.on_status('counting')
            files = list(iter_files(self.paths, settings.get('exclusions')
                                    or [], self.is_cancelled))
            limit = max(1, int(settings.get('max_file_mb') or 200)) << 20
            if self.engine == 'defender':
                import av_defender
                av_defender.scan(self, files, summary)
            else:
                self._scan_clamav(files, limit, summary)
        except EngineError as error:
            summary['error'] = str(error)
        except Exception as error:                  # noqa: BLE001
            summary['error'] = f'unexpected:{error}'
        summary['cancelled'] = self.cancelled
        summary['threats'] = len(self.findings)
        summary['seconds'] = round(time.time() - started, 1)
        try:
            av_store.add_history({
                'time': started, 'label': self.label, 'paths': self.paths,
                'engine': self.engine,
                'findings': [one.as_dict() for one in self.findings],
                **{key: summary[key] for key in
                   ('files', 'errors', 'skipped', 'seconds', 'cancelled',
                    'error')}})
        except OSError:
            pass
        self.on_done(summary)

    def _found(self, path, threat):
        finding = Finding(path, threat, self.engine)
        self.findings.append(finding)
        self.on_found(finding)

    def _scan_clamav(self, files, limit, summary):
        total = len(files)
        if not installed():
            raise EngineError('not_installed')
        if not has_databases():
            raise EngineError('no_databases')
        clamd = self.clamd
        session = None
        if clamd is not None and av_store.get('use_clamd') and locate()['clamd']:
            self.on_status('starting_engine')
            try:
                clamd.start(cancel=self.is_cancelled)
                session = clamd.session()
            except EngineError as error:
                if str(error) == 'cancelled':
                    raise
                session = None
        if session is None:
            self._scan_clamscan(files, limit, summary)
            return
        self.on_status('scanning')
        try:
            for index, path in enumerate(files, 1):
                if self.cancelled:
                    break
                try:
                    size = os.path.getsize(path)
                    if size > limit:
                        summary['skipped'] += 1
                    elif size == 0:
                        pass
                    else:
                        with open(path, 'rb') as handle:
                            status, threat = session.scan_stream(handle)
                        if status == 'found':
                            self._found(path, threat)
                        elif status == 'error':
                            summary['errors'] += 1
                except EngineError:
                    # The connection went: one more session, once.
                    session.close()
                    session = clamd.session()
                    summary['errors'] += 1
                except OSError:
                    # Locked by Windows, gone, or not ours to read.
                    summary['errors'] += 1
                summary['files'] = index
                clamd.last_used = time.time()
                self.on_progress(index, total, path)
        finally:
            session.close()

    def _scan_clamscan(self, files, limit, summary):
        """The floor: one clamscan over a list of the files, read line by
        line, which is slower to start and otherwise the same scan."""
        programs = locate()
        self.on_status('starting_engine')
        listing = os.path.join(av_store.base_folder(), 'scanlist.txt')
        wanted = [path for path in files if _size(path) <= limit]
        summary['skipped'] += len(files) - len(wanted)
        with open(listing, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(wanted))
        max_mb = limit >> 20
        command = [programs['clamscan'], f'--database={database_folder()}',
                   '--stdout', '--no-summary', f'--file-list={listing}',
                   f'--max-filesize={max_mb}M', f'--max-scansize={max_mb * 2}M']
        process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL,
                                   cwd=os.path.dirname(programs['clamscan']),
                                   **_no_window())
        total = len(wanted)
        done = 0
        try:
            for raw in iter(process.stdout.readline, b''):
                if self.cancelled:
                    process.kill()
                    break
                line = raw.decode('utf-8', 'replace').rstrip('\r\n')
                if not line or ': ' not in line:
                    continue
                if done == 0:
                    self.on_status('scanning')
                name, _, verdict = line.rpartition(': ')
                # clamscan writes the path in its own code page; the list
                # is in order, so a garbled name is matched by position.
                path = name if name in wanted else (
                    wanted[done] if done < total else name)
                if verdict.endswith(' FOUND'):
                    self._found(path, verdict[:-len(' FOUND')].strip())
                elif verdict.endswith('ERROR'):
                    summary['errors'] += 1
                done += 1
                summary['files'] = done
                self.on_progress(min(done, total), total, path)
            process.wait(timeout=30)
        finally:
            if process.poll() is None:
                process.kill()
            _remove(listing)


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
