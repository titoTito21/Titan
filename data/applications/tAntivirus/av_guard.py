# -*- coding: utf-8 -*-
"""The two things Titan Antivirus does while nobody is looking at it.

* **Watching Downloads.** A file that appears there is scanned once it has
  stopped growing, and nothing is said unless it is a threat - a guard that
  announced every clean download would be switched off within a day.
* **The scheduled scan.** Once a day at the chosen time; a day whose time
  passed while the machine was off is scanned when the guard next runs
  that day, never twice.

Both are a single slow thread with nothing to do most of the time: the
watcher reads the folder's own modification time every few seconds and
looks inside only when it has changed (a file was added or renamed), which
costs microseconds - the rule Titan's monitors follow (CLAUDE.md, "Idle
processor").
"""

import os
import threading
import time

import av_store

POLL_SECONDS = 3.0
SCHEDULE_SECONDS = 30.0
#: Names a browser writes while a download is still arriving.
PARTIAL = ('.crdownload', '.part', '.partial', '.download', '.tmp',
           '.opdownload', '!ut')


def downloads_folder():
    home = os.path.expanduser('~')
    if os.name == 'nt':
        try:
            import ctypes
            # FOLDERID_Downloads: the real one, even when the user moved it.
            path = ctypes.c_wchar_p()
            folder_id = _guid('{374DE290-123F-4565-9164-39C4925E467B}')
            if ctypes.windll.shell32.SHGetKnownFolderPath(
                    ctypes.byref(folder_id), 0, None,
                    ctypes.byref(path)) == 0:
                result = path.value
                ctypes.windll.ole32.CoTaskMemFree(path)
                if result and os.path.isdir(result):
                    return result
        except Exception:                           # noqa: BLE001
            pass
    else:
        # Linux: the XDG folder, which is "Pobrane" on a Polish desktop and
        # not "Downloads" at all.
        found = xdg_folder('DOWNLOAD')
        if found:
            return found
    return os.path.join(home, 'Downloads')


def xdg_folder(kind):
    """An XDG user folder ('DOWNLOAD', 'DESKTOP', 'DOCUMENTS') on Linux,
    or '' - Windows has its own known folders and answers ''."""
    if os.name == 'nt':
        return ''
    import subprocess
    try:
        result = subprocess.run(['xdg-user-dir', kind], capture_output=True,
                                text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return ''
    found = result.stdout.strip()
    if found and found != os.path.expanduser('~') and os.path.isdir(found):
        return found
    return ''


def _guid(text):
    import ctypes
    import uuid

    class GUID(ctypes.Structure):
        _fields_ = [('Data1', ctypes.c_ulong), ('Data2', ctypes.c_ushort),
                    ('Data3', ctypes.c_ushort), ('Data4', ctypes.c_ubyte * 8)]

    value = uuid.UUID(text)
    return GUID(value.time_low, value.time_mid, value.time_hi_version,
                (ctypes.c_ubyte * 8)(*value.bytes[8:]))


class DownloadsWatch(object):
    """Calls ``on_new(path)`` for each file that has finished arriving."""

    def __init__(self, on_new, folder=None):
        self.on_new = on_new
        self.folder = folder or downloads_folder()
        self.known = {}
        self.pending = {}
        self.folder_mtime = None

    def _listing(self):
        found = {}
        try:
            with os.scandir(self.folder) as entries:
                for entry in entries:
                    try:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        stat = entry.stat()
                    except OSError:
                        continue
                    found[entry.path] = (stat.st_size, stat.st_mtime)
        except OSError:
            return None
        return found

    def prime(self):
        """What is already there is not new."""
        self.known = self._listing() or {}
        try:
            self.folder_mtime = os.path.getmtime(self.folder)
        except OSError:
            self.folder_mtime = None

    def tick(self):
        """One look. Answers the paths handed to ``on_new`` this time."""
        try:
            mtime = os.path.getmtime(self.folder)
        except OSError:
            return []
        if mtime == self.folder_mtime and not self.pending:
            return []
        self.folder_mtime = mtime
        listing = self._listing()
        if listing is None:
            return []
        ready = []
        for path, signature in listing.items():
            if path.lower().endswith(PARTIAL):
                continue
            if self.known.get(path) == signature:
                continue
            # Seen growing last time and the same size now: finished.
            if self.pending.get(path) == signature:
                self.pending.pop(path, None)
                self.known[path] = signature
                ready.append(path)
            else:
                self.pending[path] = signature
        for path in list(self.pending):
            if path not in listing:
                self.pending.pop(path, None)
        for path in list(self.known):
            if path not in listing:
                self.known.pop(path, None)
        for path in ready:
            self.on_new(path)
        return ready


def due_today(settings, now=None):
    """True when the scheduled scan should run now and has not run today."""
    if not settings.get('schedule_enabled'):
        return False
    now = now or time.localtime()
    today = time.strftime('%Y-%m-%d', now)
    if settings.get('schedule_last_day') == today:
        return False
    try:
        hour, minute = (int(part) for part in
                        str(settings.get('schedule_time') or '12:00').split(':'))
    except ValueError:
        return False
    return (now.tm_hour, now.tm_min) >= (hour, minute)


class Guard(object):
    """The thread: the watcher when it is on, the schedule when it is on."""

    def __init__(self, on_download, on_schedule):
        self.on_download = on_download
        self.on_schedule = on_schedule
        self.watch = None
        self.stopping = threading.Event()
        self.thread = None
        self._last_schedule_check = 0.0

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopping.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True,
                                       name='TitanAntivirusGuard')
        self.thread.start()

    def stop(self):
        self.stopping.set()

    def active(self):
        settings = av_store.settings()
        return bool(settings.get('watch_downloads')
                    or settings.get('schedule_enabled'))

    def _loop(self):
        while not self.stopping.wait(POLL_SECONDS):
            settings = av_store.settings()
            if settings.get('watch_downloads'):
                if self.watch is None:
                    self.watch = DownloadsWatch(self.on_download)
                    self.watch.prime()
                else:
                    try:
                        self.watch.tick()
                    except Exception as error:      # noqa: BLE001
                        print(f'[TitanAntivirus] watch: {error}')
            else:
                self.watch = None
            now = time.time()
            if now - self._last_schedule_check >= SCHEDULE_SECONDS:
                self._last_schedule_check = now
                if due_today(settings):
                    av_store.update(
                        schedule_last_day=time.strftime('%Y-%m-%d'))
                    try:
                        self.on_schedule(settings.get('schedule_scope')
                                         or 'quick')
                    except Exception as error:      # noqa: BLE001
                        print(f'[TitanAntivirus] schedule: {error}')
