"""Titan Updater - the update that a broken Titan cannot do for itself.

Every compiled Titan up to and including 0.5.7 fails to update, always, and
the reason is one line: ``src/system/updater.py`` renames every file the
archive will overwrite to ``<name>.old`` so that Windows lets it replace the
running Titan.exe and the loaded DLLs - and the archive contains
``data/bin/7z.exe`` and ``data/bin/7z.dll`` like every other file. The
extractor therefore renamed ITSELF aside and the next line launched a file
that no longer existed: ``[WinError 2] The system cannot find the file
specified``, caught by the broad handler, rolled straight back, and reported
to the user as "Update failed. Please try again later.".

That is fixed in Titan itself, but a fix inside 0.5.7 cannot reach the
machines already running 0.5.7 - only a program from outside can. This is
that program: it updates an installed Titan from a 7z archive, with Titan
closed, and it depends on nothing inside the install (standard library only,
wx used for the window only if it happens to be importable).

Usage
-----
    titan_updater.py [ARCHIVE ...] [options]

    ARCHIVE            a .7z to apply. With none given, any titan*.7z beside
                       the updater or in the install directory is used, and
                       failing that the current one is downloaded.

    --install-dir DIR  where Titan is (default: found automatically)
    --download         ignore local archives and download the current ones
    --console          never open a window, even where wx is available
    --no-launch        do not offer to start Titan afterwards
    --yes              answer every question with yes (unattended)

The rule this file is built on, learned from the bug above: **the tool doing
the work must stand outside the tree it is rewriting.** 7-Zip is copied to a
temporary directory and run from there, so the update can freely replace the
7-Zip that is inside the install.
"""

import argparse
import ctypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

VERSION_URL = "https://titosofttitan.com/titan/titanchk/version.ver"
MAIN_URL = "https://titosofttitan.com/titan/titan.main.7z"
INTERPRETER_URL = "https://titosofttitan.com/titan/titan.interpreter.7z"

# Where Titan is normally installed, used when nothing better is found.
DEFAULT_INSTALL = r"C:\Titan\titan_data"

IS_WINDOWS = sys.platform == 'win32'


def _no_window():
    """Subprocess flags that keep console windows from flashing up."""
    if not IS_WINDOWS:
        return {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {'startupinfo': info, 'creationflags': subprocess.CREATE_NO_WINDOW}


def here():
    """The directory this updater is running from (script or frozen exe)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def bundled_dir():
    """Where files packed with a onefile build are unpacked to."""
    return getattr(sys, '_MEIPASS', here())


class UpdateError(Exception):
    """Something went wrong that the user has to be told about."""


class TitanUpdate:
    """Apply one or more Titan archives to an installed Titan.

    Knows nothing about wx: it reports through ``progress(percent, text)``
    and raises UpdateError when it cannot go on, so the console front end and
    the window front end drive exactly the same code.
    """

    def __init__(self, install_dir, progress=None):
        self.install_dir = os.path.abspath(install_dir)
        self.progress = progress or (lambda percent, text=None: None)
        self._extractor = None
        self._extractor_dir = None

    # ---------------------------------------------------------------- setup

    def check_install(self):
        """Refuse to write into something that is not a Titan install.

        Extracting 7 800 files into the wrong folder is not a mistake that
        can be undone by hand, so the directory has to look like Titan
        before anything is touched.
        """
        if not os.path.isdir(self.install_dir):
            raise UpdateError(
                "There is no folder at {}.".format(self.install_dir))
        looks_like_titan = (
            os.path.exists(os.path.join(self.install_dir, 'Titan.exe'))
            or os.path.isdir(os.path.join(self.install_dir, '_internal'))
            or os.path.isdir(os.path.join(self.install_dir, 'data'))
        )
        if not looks_like_titan:
            raise UpdateError(
                "{} does not look like a Titan installation (no Titan.exe, "
                "no _internal and no data folder).".format(self.install_dir))

    def resolve_extractor(self):
        """A 7-Zip that the update cannot pull out from under itself.

        Preference order: the copy packed with this updater, then Titan's own
        ``data/bin/7z.exe``, then a 7-Zip installed on the machine. Whichever
        it is, it is copied - with the DLLs beside it, because 7z.exe decodes
        nothing without 7z.dll - into a temporary directory and run from
        there. That is the whole point of this program: the extractor must
        not be a file the archive is about to replace.
        """
        if self._extractor is not None:
            return self._extractor

        candidates = [
            os.path.join(bundled_dir(), '7z.exe'),
            os.path.join(here(), '7z.exe'),
            os.path.join(self.install_dir, 'data', 'bin', '7z.exe'),
        ]
        found = shutil.which('7z')
        if found:
            candidates.append(found)

        source = next((c for c in candidates if os.path.exists(c)), None)
        if source is None:
            raise UpdateError(
                "7-Zip could not be found. Put 7z.exe and 7z.dll next to this "
                "updater, or install 7-Zip.")

        self._extractor_dir = tempfile.mkdtemp(prefix='titan_update_7z_')
        target = os.path.join(self._extractor_dir, '7z.exe')
        shutil.copy2(source, target)
        source_dir = os.path.dirname(os.path.abspath(source))
        for name in os.listdir(source_dir):
            if name.lower().endswith('.dll'):
                try:
                    shutil.copy2(os.path.join(source_dir, name),
                                 os.path.join(self._extractor_dir, name))
                except Exception:
                    pass
        self._extractor = target
        return self._extractor

    def release(self):
        """Remove the temporary 7-Zip."""
        directory, self._extractor_dir, self._extractor = (
            self._extractor_dir, None, None)
        if directory:
            shutil.rmtree(directory, ignore_errors=True)

    # ------------------------------------------------------------- the app

    def titan_running(self):
        """PIDs of Titan processes running out of THIS install.

        Asked of Windows directly rather than through wmic (removed from
        recent Windows 11 builds) or PowerShell (about a second per launch,
        and this is polled while waiting for Titan to close). Matched on the
        image path, not on the name: another Titan.exe elsewhere on the
        machine is not ours to wait for.
        """
        if not IS_WINDOWS:
            return []

        TH32CS_SNAPPROCESS = 0x2
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        INVALID_HANDLE = ctypes.c_void_p(-1).value

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ('dwSize', ctypes.c_ulong),
                ('cntUsage', ctypes.c_ulong),
                ('th32ProcessID', ctypes.c_ulong),
                ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)),
                ('th32ModuleID', ctypes.c_ulong),
                ('cntThreads', ctypes.c_ulong),
                ('th32ParentProcessID', ctypes.c_ulong),
                ('pcPriClassBase', ctypes.c_long),
                ('dwFlags', ctypes.c_ulong),
                ('szExeFile', ctypes.c_wchar * 260),
            ]

        kernel32 = ctypes.windll.kernel32
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == INVALID_HANDLE:
            return []

        root = os.path.normcase(self.install_dir)
        pids = []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                if entry.szExeFile.lower() == 'titan.exe':
                    path = self._process_path(entry.th32ProcessID,
                                              PROCESS_QUERY_LIMITED_INFORMATION)
                    # A process we cannot open at all (a Titan running as
                    # another user) is still a Titan in the way, so it counts
                    # unless we can prove it lives somewhere else.
                    if path is None or os.path.normcase(
                            os.path.dirname(path)).startswith(root):
                        pids.append(entry.th32ProcessID)
                more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        return sorted(set(pids))

    @staticmethod
    def _process_path(pid, access):
        """Full image path of a process, or None when Windows will not say."""
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(access, False, pid)
        if not handle:
            return None
        try:
            size = ctypes.c_ulong(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(
                    handle, 0, buffer, ctypes.byref(size)):
                return buffer.value
            return None
        finally:
            kernel32.CloseHandle(handle)

    def close_titan(self, timeout=30.0):
        """Ask the running Titan to close, then wait for it to really go.

        A polite close first (Titan then saves its settings and puts its own
        windows away); only a process that has ignored that for the whole
        timeout is killed, because killing Titan mid-write is how a settings
        file ends up truncated.
        """
        pids = self.titan_running()
        if not pids:
            return True
        for pid in pids:
            try:
                subprocess.run(['taskkill', '/PID', str(pid)],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, **_no_window())
            except Exception:
                pass

        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.titan_running():
                # Windows releases the file handles a moment after the process
                # object goes; extracting into them immediately still fails.
                time.sleep(1.0)
                return True
            time.sleep(0.5)

        for pid in self.titan_running():
            try:
                subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, **_no_window())
            except Exception:
                pass
        time.sleep(1.5)
        return not self.titan_running()

    # ------------------------------------------------------------ download

    def download(self, url, destination, label):
        """Fetch one archive, reporting real progress."""
        self.progress(0, label)
        try:
            request = urllib.request.Request(
                url, headers={'User-Agent': 'TitanUpdater'})
            with urllib.request.urlopen(request, timeout=30) as response:
                total = int(response.headers.get('content-length') or 0)
                done = 0
                last = -1
                with open(destination, 'wb') as handle:
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        handle.write(chunk)
                        done += len(chunk)
                        if total:
                            percent = int(done * 100 / total)
                            if percent != last:
                                last = percent
                                self.progress(percent, label)
        except Exception as e:
            raise UpdateError("Could not download {}: {}".format(url, e))
        return destination

    # ------------------------------------------------------------- extract

    def archive_entries(self, archive):
        """(relative path, is a directory) for everything in the archive."""
        entries = []
        out = subprocess.run(
            [self.resolve_extractor(), 'l', '-slt', archive],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            **_no_window()).stdout.decode('utf-8', 'replace')

        in_files = False
        path = None
        attributes = ''
        for line in out.splitlines():
            if not in_files:
                if line.strip().startswith('----------'):
                    in_files = True
                continue
            if line.startswith('Path = '):
                path, attributes = line[len('Path = '):].strip(), ''
            elif line.startswith('Attributes = '):
                attributes = line[len('Attributes = '):].strip()
            elif line.strip() == '' and path is not None:
                entries.append((path, 'D' in attributes))
                path, attributes = None, ''
        if path is not None:
            entries.append((path, 'D' in attributes))
        return entries

    def stage(self, archive, staged):
        """Move aside every file the archive will overwrite.

        With Titan closed nothing is locked and a plain overwrite would do -
        but staging is also what makes the update reversible, and an update
        that cannot be undone is the one thing worse than an update that
        fails. Each record says exactly how to put the install back:

          ('rename', <name>.old, <name>) - the file that was there
          ('new',    <name>,     None)   - a file the archive adds
        """
        for relative, is_dir in self.archive_entries(archive):
            if is_dir:
                continue
            target = os.path.join(self.install_dir,
                                  relative.replace('/', os.sep))
            if not os.path.exists(target):
                staged.append(('new', target, None))
                continue

            old = target + '.old'
            try:
                if os.path.exists(old):
                    os.remove(old)
            except Exception:
                old = target + '.old{}'.format(int(time.time() * 1000) % 100000)
            try:
                os.replace(target, old)
                staged.append(('rename', old, target))
            except Exception as e:
                raise UpdateError(
                    "{} is in use and could not be replaced ({}). Close Titan "
                    "and anything started from it, then try again."
                    .format(target, e))

    def rollback(self, staged):
        """Put the install back exactly as it was."""
        for kind, first, second in reversed(staged):
            try:
                if kind == 'rename':
                    old, target = first, second
                    if os.path.exists(target):
                        os.remove(target)
                    os.replace(old, target)
                elif kind == 'new' and os.path.exists(first):
                    os.remove(first)
            except Exception as e:
                print("Rollback failed for {}: {}".format(first, e))

    def extract(self, archive, label, staged):
        """Extract one archive over the install, with progress."""
        self.progress(0, label)
        if not os.path.exists(archive):
            raise UpdateError("The archive {} does not exist.".format(archive))

        self.stage(archive, staged)

        process = subprocess.Popen(
            [self.resolve_extractor(), 'x', archive, '-y', '-aoa',
             '-o{}'.format(self.install_dir), '-bsp1'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_no_window())

        # stderr is drained on a thread of its own: 7-Zip writing more than
        # the pipe buffer holds while nobody reads it is a deadlock, and an
        # update that hangs for ever is indistinguishable from a crash.
        errors = []
        drain = threading.Thread(
            target=lambda: errors.append(process.stderr.read()), daemon=True)
        drain.start()

        buffer = b''
        last = -1
        while True:
            chunk = process.stdout.read(512)
            if not chunk:
                break
            buffer += chunk
            while True:
                positions = [p for p in (buffer.find(b'\r'), buffer.find(b'\n'))
                             if p != -1]
                if not positions:
                    break
                cut = min(positions)
                line = buffer[:cut].decode('utf-8', 'replace').strip()
                buffer = buffer[cut + 1:]
                match = re.match(r'(\d+)%', line)
                if match:
                    percent = int(match.group(1))
                    if percent != last:
                        last = percent
                        self.progress(percent, label)

        code = process.wait()
        drain.join(timeout=5)
        for pipe in (process.stdout, process.stderr):
            try:
                pipe.close()
            except Exception:
                pass
        if code != 0:
            text = b''.join(c for c in errors if c).decode('utf-8', 'replace')
            raise UpdateError(
                "7-Zip could not unpack {} (exit code {}).{}".format(
                    os.path.basename(archive), code,
                    "\n" + text.strip() if text.strip() else ""))
        self.progress(100, label)

    # --------------------------------------------------------------- after

    def clean_old(self):
        """Delete the ``.old`` files left by the staging above.

        Only where the live file exists - that is the proof it was one of
        ours, and it is what keeps an unrelated user file that merely ends in
        ``.old`` safe.
        """
        removed = 0
        for root, dirs, files in os.walk(self.install_dir):
            if 'pkg_cache' in dirs:
                dirs.remove('pkg_cache')
            for name in files:
                # Exactly what stage() writes: <name>.old, or <name>.old1234
                # when a previous .old was still held.
                if not re.search(r'\.old\d*$', name):
                    continue
                path = os.path.join(root, name)
                live = re.sub(r'\.old\d*$', '', path)
                # The live file existing is the proof this .old is one of
                # ours - it is what keeps an unrelated user file safe.
                if not os.path.exists(live):
                    continue
                try:
                    os.remove(path)
                    removed += 1
                except Exception:
                    pass
        return removed

    def launch(self):
        """Start the Titan that has just been installed."""
        exe = os.path.join(self.install_dir, 'Titan.exe')
        if not os.path.exists(exe):
            return False
        try:
            subprocess.Popen([exe], cwd=self.install_dir)
            return True
        except Exception:
            return False

    # ----------------------------------------------------------- the whole

    def run(self, archives, temp_dir=None):
        """Apply every archive as one update: all of it, or none of it.

        The archives share ONE rollback set on purpose. A Titan whose
        program was replaced but whose interpreter was not does not start,
        so a failure in the second archive has to undo the first as well.
        """
        self.check_install()
        self.resolve_extractor()

        staged = []
        try:
            for index, archive in enumerate(archives, 1):
                label = "Unpacking {} ({} of {})...".format(
                    os.path.basename(archive), index, len(archives))
                self.extract(archive, label, staged)
        except Exception:
            self.progress(0, "Undoing the update...")
            self.rollback(staged)
            raise

        self.progress(100, "Tidying up...")
        self.clean_old()
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
        return True


# --------------------------------------------------------------------------
# Finding the install and the archives
# --------------------------------------------------------------------------

def find_install(explicit=None):
    """Where Titan is. Beside the updater first - that is where it belongs."""
    if explicit:
        return os.path.abspath(explicit)

    candidates = [
        here(),                                  # dropped into the install
        os.path.join(here(), 'titan_data'),      # dropped beside it
        DEFAULT_INSTALL,
        os.path.join(os.path.dirname(here()), 'titan_data'),
    ]
    for candidate in candidates:
        if os.path.exists(os.path.join(candidate, 'Titan.exe')):
            return os.path.abspath(candidate)
    return DEFAULT_INSTALL


def find_archives(install_dir, explicit=None):
    """The archives to apply: what was asked for, or what is lying about.

    A local archive is preferred over a download because that is the whole
    point of this tool - the user may already have the 236 MB file, and on a
    slow connection downloading it again is the difference between an update
    and an afternoon.
    """
    if explicit:
        missing = [a for a in explicit if not os.path.exists(a)]
        if missing:
            raise UpdateError(
                "These archives do not exist: {}".format(', '.join(missing)))
        return [os.path.abspath(a) for a in explicit]

    found = []
    for folder in (here(), install_dir):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            lower = name.lower()
            if not lower.endswith('.7z'):
                continue
            if not (lower.startswith('titan') or lower.startswith('tce')):
                continue
            path = os.path.abspath(os.path.join(folder, name))
            if path not in found:
                found.append(path)

    # The program has to be unpacked before the interpreter, or a fresh
    # Titan.exe would be left sitting on the old _internal for a moment.
    found.sort(key=lambda p: 'interpreter' in os.path.basename(p).lower())
    return found


def remote_version():
    """The version the server is offering, and whether it needs the
    interpreter package (that is what the trailing 'i' has always meant)."""
    try:
        request = urllib.request.Request(
            VERSION_URL, headers={'User-Agent': 'TitanUpdater'})
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode('utf-8', 'replace').strip()
    except Exception:
        return None, False
    if raw.endswith('i'):
        return raw[:-1], True
    return raw, False


def download_archives(update, temp_dir):
    """Fetch the current archives from titosofttitan.com."""
    version, needs_interpreter = remote_version()
    archives = [update.download(
        MAIN_URL, os.path.join(temp_dir, 'titan.main.7z'),
        "Downloading Titan{}...".format(" " + version if version else ""))]
    if needs_interpreter:
        archives.append(update.download(
            INTERPRETER_URL, os.path.join(temp_dir, 'titan.interpreter.7z'),
            "Downloading the Python interpreter..."))
    return archives


# --------------------------------------------------------------------------
# The console front end
# --------------------------------------------------------------------------

class ConsoleUI:
    """Plain text, because a console is read by every screen reader.

    Progress is announced in tens, not in ones: a reader saying every one of
    a hundred numbers is a reader saying nothing useful for a minute.
    """

    def __init__(self, assume_yes=False):
        self.assume_yes = assume_yes
        self._last_step = -1
        self._last_label = None

    def progress(self, percent, text=None):
        if text and text != self._last_label:
            self._last_label = text
            self._last_step = -1
            print("\n" + text)
        step = int(percent) // 10
        if step != self._last_step:
            self._last_step = step
            print("  {}%".format(step * 10))

    def ask(self, question):
        if self.assume_yes:
            print("{} yes".format(question))
            return True
        if sys.stdin is None or not sys.stdin.readable():
            # A windowed build whose wx could not be loaded has no console to
            # ask in. Somebody who started an updater wants to update, so the
            # question is answered rather than turned into a failure.
            return True
        try:
            answer = input("{} [Y/n] ".format(question)).strip().lower()
        except (EOFError, KeyboardInterrupt, RuntimeError, OSError):
            return False
        return answer in ('', 'y', 'yes', 't', 'tak')

    def say(self, text):
        print(text)

    def fail(self, text):
        print("\n" + text)


def run_console(args):
    ui = ConsoleUI(assume_yes=args.yes)
    install = find_install(args.install_dir)
    update = TitanUpdate(install, progress=ui.progress)
    temp_dir = None

    ui.say("Titan Updater")
    ui.say("Installation: {}".format(install))

    try:
        update.check_install()

        if update.titan_running():
            if not ui.ask("Titan is running and has to be closed. Close it?"):
                ui.fail("The update was not started.")
                return 1
            ui.say("Closing Titan...")
            if not update.close_titan():
                ui.fail("Titan could not be closed. Close it by hand and run "
                        "this updater again.")
                return 1

        archives = ([] if args.download
                    else find_archives(install, args.archives))
        if not archives:
            temp_dir = tempfile.mkdtemp(prefix='titan_update_')
            archives = download_archives(update, temp_dir)
        else:
            ui.say("Using: {}".format(
                ', '.join(os.path.basename(a) for a in archives)))

        update.run(archives, temp_dir=temp_dir)
        ui.say("\nTitan has been updated.")

        if not args.no_launch and ui.ask("Start Titan now?"):
            update.launch()
        return 0

    except UpdateError as e:
        ui.fail("The update failed. Nothing was changed.\n\n{}".format(e))
        return 1
    except Exception as e:
        ui.fail("The update failed. Nothing was changed.\n\n{}".format(e))
        return 1
    finally:
        update.release()
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


# --------------------------------------------------------------------------
# The window front end
# --------------------------------------------------------------------------

def run_gui(args):
    """The same update, in a window, when wx is available.

    Accessibility here is the ordinary kind: real wx controls, a real
    wx.Gauge, and the status in a read-only text field rather than a static
    label - a field can be focused, so the user can read the current step
    back at any time instead of having to catch it as it is said.
    """
    import wx

    class UpdaterFrame(wx.Frame):
        def __init__(self):
            super().__init__(None, title="Titan Updater",
                             style=wx.DEFAULT_FRAME_STYLE & ~wx.MAXIMIZE_BOX)
            panel = wx.Panel(self)
            sizer = wx.BoxSizer(wx.VERTICAL)

            self.install = find_install(args.install_dir)
            self.update = TitanUpdate(self.install, progress=self.on_progress)
            self.temp_dir = None
            self.busy = False

            sizer.Add(wx.StaticText(panel, label="Installation:"),
                      0, wx.LEFT | wx.TOP, 10)
            self.install_field = wx.TextCtrl(panel, value=self.install,
                                             style=wx.TE_READONLY)
            sizer.Add(self.install_field, 0, wx.ALL | wx.EXPAND, 10)

            sizer.Add(wx.StaticText(panel, label="Status:"), 0, wx.LEFT, 10)
            self.status = wx.TextCtrl(
                panel, value="Ready to update Titan.",
                style=wx.TE_READONLY | wx.TE_MULTILINE, size=(430, 90))
            sizer.Add(self.status, 1, wx.ALL | wx.EXPAND, 10)

            self.gauge = wx.Gauge(panel, range=100, size=(430, -1))
            sizer.Add(self.gauge, 0, wx.ALL | wx.EXPAND, 10)

            buttons = wx.BoxSizer(wx.HORIZONTAL)
            self.start_button = wx.Button(panel, label="&Update Titan")
            self.close_button = wx.Button(panel, wx.ID_CANCEL, "&Close")
            buttons.Add(self.start_button, 0, wx.RIGHT, 10)
            buttons.Add(self.close_button, 0)
            sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_CENTER, 10)

            panel.SetSizer(sizer)
            self.Fit()
            self.Centre()

            self.start_button.Bind(wx.EVT_BUTTON, self.on_start)
            self.close_button.Bind(wx.EVT_BUTTON, lambda e: self.Close())
            self.Bind(wx.EVT_CLOSE, self.on_close)
            self.start_button.SetFocus()

        # -- reporting

        def on_progress(self, percent, text=None):
            wx.CallAfter(self._on_progress, percent, text)

        def _on_progress(self, percent, text):
            try:
                self.gauge.SetValue(max(0, min(100, int(percent))))
                if text and text != self.status.GetValue():
                    self.status.SetValue(text)
            except RuntimeError:
                pass

        def say(self, text):
            wx.CallAfter(self._say, text)

        def _say(self, text):
            try:
                self.status.SetValue(text)
            except RuntimeError:
                pass

        # -- the work

        def on_start(self, event):
            if self.busy:
                return
            if self.update.titan_running():
                answer = wx.MessageBox(
                    "Titan is running and has to be closed before it can be "
                    "updated.\n\nClose it now?", "Titan Updater",
                    wx.YES_NO | wx.ICON_QUESTION, self)
                if answer != wx.YES:
                    return

            self.busy = True
            self.start_button.Enable(False)
            self.close_button.Enable(False)
            threading.Thread(target=self.work, daemon=True).start()

        def work(self):
            try:
                self.update.check_install()

                if self.update.titan_running():
                    self.say("Closing Titan...")
                    if not self.update.close_titan():
                        raise UpdateError(
                            "Titan could not be closed. Close it by hand and "
                            "run this updater again.")

                archives = ([] if args.download
                            else find_archives(self.install, args.archives))
                if not archives:
                    self.temp_dir = tempfile.mkdtemp(prefix='titan_update_')
                    archives = download_archives(self.update, self.temp_dir)

                self.update.run(archives, temp_dir=self.temp_dir)
                self.temp_dir = None
                wx.CallAfter(self.finished)
            except Exception as e:
                wx.CallAfter(self.failed, str(e))

        def finished(self):
            self.busy = False
            self.update.release()
            self.gauge.SetValue(100)
            self.status.SetValue("Titan has been updated.")
            self.close_button.Enable(True)
            self.close_button.SetFocus()
            if not args.no_launch:
                answer = wx.MessageBox(
                    "Titan has been updated.\n\nStart it now?",
                    "Titan Updater", wx.YES_NO | wx.ICON_INFORMATION, self)
                if answer == wx.YES:
                    self.update.launch()
            self.Close()

        def failed(self, message):
            self.busy = False
            self.update.release()
            self.gauge.SetValue(0)
            self.status.SetValue(
                "The update failed. Nothing was changed.\n\n" + message)
            self.start_button.Enable(True)
            self.close_button.Enable(True)
            self.status.SetFocus()
            wx.MessageBox(
                "The update failed and the installation was left exactly as "
                "it was.\n\n" + message, "Titan Updater",
                wx.OK | wx.ICON_ERROR, self)

        def on_close(self, event):
            if self.busy:
                answer = wx.MessageBox(
                    "The update is still running. Stopping now can leave "
                    "Titan half-updated.\n\nClose anyway?", "Titan Updater",
                    wx.YES_NO | wx.ICON_WARNING, self)
                if answer != wx.YES:
                    event.Veto()
                    return
            self.update.release()
            if self.temp_dir:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            event.Skip()

    app = wx.App(False)
    UpdaterFrame().Show()
    app.MainLoop()
    return 0


# --------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog='titan_updater',
        description="Update an installed Titan from a 7z archive.")
    parser.add_argument('archives', nargs='*', metavar='ARCHIVE',
                        help="archives to apply (default: found automatically)")
    parser.add_argument('--install-dir', default=None,
                        help="where Titan is installed")
    parser.add_argument('--download', action='store_true',
                        help="download the current archives instead of using "
                             "local ones")
    parser.add_argument('--console', action='store_true',
                        help="never open a window")
    parser.add_argument('--no-launch', action='store_true',
                        help="do not offer to start Titan afterwards")
    parser.add_argument('--yes', action='store_true',
                        help="answer every question with yes")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    # An archive named on the command line is what the user meant, whichever
    # front end runs.
    if args.archives:
        try:
            args.archives = find_archives(find_install(args.install_dir),
                                          args.archives)
        except UpdateError as e:
            print(str(e))
            return 1

    if args.console or args.archives or args.yes:
        return run_console(args)

    try:
        return run_gui(args)
    except ImportError:
        return run_console(args)


if __name__ == '__main__':
    if IS_WINDOWS:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    sys.exit(main())
