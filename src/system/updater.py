import wx
import threading
import time
import requests
import os
import sys
import subprocess
import shutil
import re
import tempfile
import traceback
# Everything this module will ever need is imported HERE, never inside a
# function that runs after the archive has been unpacked. In the frozen
# build the modules live in the PYZ inside Titan.exe, and once extraction
# has put the NEW Titan.exe in place a first import reads the new file at
# the old offsets: "zlib.error: incorrect header check", measured, from an
# `import filecmp` three lines after a successful extraction.
import filecmp
from src.titan_core.sound import play_sound, play_focus_sound, play_select_sound
from src.titan_core.translation import _
from src.platform_utils import get_subprocess_kwargs, get_base_path, is_frozen, IS_WINDOWS
from src.titan_core.skin_manager import apply_skin_to_window


# ---------------------------------------------------------------------------
# What the updater did is written down.
#
# A compiled Titan is built with --windowed, so sys.stdout is None and every
# print() in this file reached nobody: an update that failed on every attempt
# was reported as "Update failed. Please try again later." and not one word
# more, and the only way to find out WHY was to reproduce it in a source
# checkout - where the frozen process's own circumstances (the running exe,
# the loaded DLLs, the bundled py7zr, the inherited PATH) are not there to be
# reproduced.  Everything the updater says therefore also goes to
# %APPDATA%/titosoft/Titan/logs/update.log, and the failure dialog names the
# reason and the file.
# ---------------------------------------------------------------------------

LOG_NAME = 'update.log'
#: The log is started again once it has grown past this many bytes.
LOG_ROTATE_AT = 2 * 1024 * 1024
_log_lock = threading.Lock()


def log_dir():
    """The folder the update log is written to."""
    try:
        from src.platform_utils import ensure_user_data_subdir
        path = ensure_user_data_subdir('logs')
        if os.path.isdir(path):
            return path
    except Exception:
        pass
    return tempfile.gettempdir()


def log_path():
    return os.path.join(log_dir(), LOG_NAME)


def log(message):
    """Print the line AND append it to the update log.

    Neither may ever raise: this is called from inside except blocks on the
    worker thread, where an exception would turn the one honest report of a
    failure into a second, meaningless one.
    """
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    try:
        print(line)
    except Exception:
        pass
    try:
        with _log_lock:
            path = log_path()
            try:
                if os.path.getsize(path) > LOG_ROTATE_AT:
                    os.replace(path, path + '.1')
            except OSError:
                pass
            with open(path, 'a', encoding='utf-8') as handle:
                handle.write(line + '\n')
    except Exception:
        pass


#: 7z coder ids worth naming in a log line (the hex of the method id).
_METHOD_NAMES = {
    '00': 'Copy', '21': 'LZMA2', '030101': 'LZMA', '03': 'Delta',
    '03030103': 'BCJ', '0303011b': 'BCJ2', '03030205': 'PPC',
    '03030401': 'IA64', '03030501': 'ARM', '03030701': 'ARMT',
    '03030805': 'SPARC', '0a': 'ARM64', '0b': 'RISCV', '04': 'PPMd',
    '040108': 'Deflate', '040109': 'Deflate64', '040202': 'BZip2',
    '04f71101': 'Zstandard', '04f71102': 'Brotli', '06f10701': 'AES',
}


def _method_name(coder):
    method = coder.get('method') if isinstance(coder, dict) else None
    if not method:
        return '?'
    key = bytes(method).hex()
    return _METHOD_NAMES.get(key, key)


def _apply_skin_to_tree(window):
    """Apply current skin to a window and all descendants."""
    try:
        apply_skin_to_window(window)
    except Exception:
        return

    for child in window.GetChildren():
        _apply_skin_to_tree(child)

class UpdateDialog(wx.Dialog):
    def __init__(self, parent, current_version, new_version, changes):
        super().__init__(parent, title=_("Program Update Available"), 
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        
        self.current_version = current_version
        self.new_version = new_version
        self.changes = changes
        
        self.init_ui()
        self.bind_events()
        _apply_skin_to_tree(self)
        
        # Play newupdate sound 3 seconds before showing dialog
        wx.CallAfter(self.delayed_show)
    
    def init_ui(self):
        """Initialize the user interface."""
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Title label
        title_label = wx.StaticText(self, label=_("Program update is available"))
        title_font = title_label.GetFont()
        title_font.SetWeight(wx.FONTWEIGHT_BOLD)
        title_label.SetFont(title_font)
        main_sizer.Add(title_label, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        # Version info
        info_sizer = wx.FlexGridSizer(2, 2, 5, 10)
        info_sizer.AddGrowableCol(1, 1)
        
        # Current version
        current_label = wx.StaticText(self, label=_("Current version:"))
        self.current_text = wx.TextCtrl(self, value=self.current_version, 
                                       style=wx.TE_READONLY)
        info_sizer.Add(current_label, 0, wx.ALIGN_CENTER_VERTICAL)
        info_sizer.Add(self.current_text, 1, wx.EXPAND)
        
        # New version
        new_label = wx.StaticText(self, label=_("Update to version:"))
        self.new_text = wx.TextCtrl(self, value=self.new_version, 
                                   style=wx.TE_READONLY)
        info_sizer.Add(new_label, 0, wx.ALIGN_CENTER_VERTICAL)
        info_sizer.Add(self.new_text, 1, wx.EXPAND)
        
        main_sizer.Add(info_sizer, 0, wx.ALL | wx.EXPAND, 10)
        
        # Changes text
        changes_label = wx.StaticText(self, label=_("What's new:"))
        main_sizer.Add(changes_label, 0, wx.LEFT | wx.RIGHT, 10)
        
        self.changes_text = wx.TextCtrl(self, value=self.changes, 
                                       style=wx.TE_MULTILINE | wx.TE_READONLY)
        self.changes_text.SetMinSize((400, 200))
        main_sizer.Add(self.changes_text, 1, wx.ALL | wx.EXPAND, 10)
        
        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        self.update_btn = wx.Button(self, wx.ID_OK, _("Update"))
        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("Cancel"))
        
        button_sizer.Add(self.update_btn, 0, wx.RIGHT, 5)
        button_sizer.Add(self.cancel_btn, 0)
        
        main_sizer.Add(button_sizer, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        self.SetSizer(main_sizer)
        self.Fit()
        self.CenterOnParent()
    
    def bind_events(self):
        """Bind control events."""
        self.current_text.Bind(wx.EVT_SET_FOCUS, self.on_focus)
        self.new_text.Bind(wx.EVT_SET_FOCUS, self.on_focus)
        self.changes_text.Bind(wx.EVT_SET_FOCUS, self.on_focus)
        self.update_btn.Bind(wx.EVT_SET_FOCUS, self.on_focus)
        self.cancel_btn.Bind(wx.EVT_SET_FOCUS, self.on_focus)
        
        self.update_btn.Bind(wx.EVT_BUTTON, self.on_select)
        self.cancel_btn.Bind(wx.EVT_BUTTON, self.on_select)
    
    def on_focus(self, event):
        """Play focus sound when control receives focus."""
        play_focus_sound()
        event.Skip()
    
    def on_select(self, event):
        """Play select sound when button is clicked."""
        play_select_sound()
        event.Skip()
    
    def delayed_show(self):
        """Show dialog after playing newupdate sound."""
        # Play newupdate sound
        play_sound('system/newupdate.ogg')

        # Wait 3 seconds then show dialog with safety check
        wx.CallLater(3000, self.safe_show)
    
    def safe_show(self):
        """Safely show dialog with existence check."""
        try:
            if self and not self.IsBeingDeleted():
                self.Show()
        except RuntimeError:
            # Dialog was already deleted
            pass


class ProgressDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Downloading Update"), 
                        style=wx.DEFAULT_DIALOG_STYLE)
        
        self.init_ui()
        _apply_skin_to_tree(self)

        # Start playing installation sound in background
        play_sound('system/installingapps.ogg')

    def init_ui(self):
        """Initialize progress dialog UI."""
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Status label
        self.status_label = wx.StaticText(self, label=_("Downloading update..."))
        main_sizer.Add(self.status_label, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        # Progress bar
        self.progress_bar = wx.Gauge(self, range=100)
        self.progress_bar.SetMinSize((300, -1))
        main_sizer.Add(self.progress_bar, 0, wx.ALL | wx.EXPAND, 10)
        
        # Cancel button
        self.cancel_btn = wx.Button(self, wx.ID_CANCEL, _("Cancel"))
        main_sizer.Add(self.cancel_btn, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        
        self.SetSizer(main_sizer)
        self.Fit()
        self.CenterOnParent()
    
    def update_progress(self, progress, status_text=None):
        """Update progress bar and status text."""
        wx.CallAfter(self._update_progress, progress, status_text)
    
    def _update_progress(self, progress, status_text):
        """Internal method to update progress on main thread."""
        try:
            self.progress_bar.SetValue(progress)
            if status_text:
                self.status_label.SetLabel(status_text)
        except RuntimeError:
            # Dialog was already destroyed - ignore late progress events.
            pass


# How long the startup check may wait for the update server: (connect, read).
# It runs before Titan has a window, and an unreachable server must cost a
# moment rather than ten seconds of a program that appears not to have
# started.
STARTUP_CHECK_TIMEOUT = (3.05, 4.0)


class Updater:
    def __init__(self, parent=None):
        self.parent = parent
        self.version_url = "https://titosofttitan.com/titan/titanchk/version.ver"
        self.changes_url = "https://titosofttitan.com/titan/titanchk/changes.txt"
        self.download_url = "https://titosofttitan.com/titan/titan.main.7z"
        self.interpreter_url = "https://titosofttitan.com/titan/titan.interpreter.7z"

        # Resolve install dir so the updater works regardless of cwd.
        # In compiled mode this is the directory containing Titan.exe;
        # in dev mode it is the project root.
        self.install_dir = get_base_path()

        # Absolute paths for downloaded archives and 7z so that a wrong cwd
        # cannot break the update.
        self.temp_file = os.path.join(self.install_dir, "titan_update.7z")
        self.temp_interpreter_file = os.path.join(
            self.install_dir, "titan_interpreter.7z"
        )

        if sys.platform == 'win32':
            bundled_7z = os.path.join(self.install_dir, "data", "bin", "7z.exe")
            self.seven_zip_path = (
                bundled_7z if os.path.exists(bundled_7z)
                else (shutil.which("7z") or bundled_7z)
            )
        else:
            self.seven_zip_path = shutil.which("7z") or "7z"

        # 7-Zip actually used for the extraction. It is NOT self.seven_zip_path
        # when that one lives inside the install directory - see
        # _resolve_extractor() for why the extractor must stand outside the
        # tree it is rewriting.
        self._extractor = None
        self._extractor_dir = None

        self.needs_interpreter = False  # Will be set if version ends with 'i'

        # Why the last step failed, in one sentence a person can act on. The
        # failure dialog shows it; the log has the rest.
        self.failure_reason = None
        # Files the running Titan held open while they were being replaced
        # (see _move_aside) and anything the rollback could not put back.
        self.files_in_use = []
        self.rollback_problems = []

    # Defaults for an instance built without __init__ (the tests do that).
    failure_reason = None
    files_in_use = ()
    rollback_problems = ()

    def _fail(self, reason):
        """Record why the update is failing and log it. Returns False so a
        failing branch can ``return self._fail(...)``."""
        self.failure_reason = reason
        log(f"[UPDATER] FAILED: {reason}")
        return False

    def _log_environment(self):
        """The facts a failure report needs, written before anything is done."""
        try:
            import py7zr  # noqa: F401
            have_py7zr = getattr(py7zr, '__version__', 'yes')
        except Exception as e:
            have_py7zr = f"no ({e})"
        log(f"[UPDATER] install_dir={self.install_dir} frozen={is_frozen()} "
            f"executable={sys.executable} platform={sys.platform} "
            f"python={sys.version.split()[0]}")
        log(f"[UPDATER] bundled 7-Zip: {self.seven_zip_path} "
            f"(exists={os.path.exists(self.seven_zip_path)}); "
            f"7z on PATH: {shutil.which('7z')}; py7zr: {have_py7zr}")

    def get_current_version(self):
        """Get current program version from the running main module.

        When Titan is launched normally the entry script is loaded as
        ``__main__`` (both in dev and in a frozen build), so read VERSION
        from there first. Doing ``import main`` in a frozen build fails
        (there is no importable ``main`` module) and, in dev, re-executes
        main.py as a second module - both are wrong, so they are only a
        last resort. Returns None when the version cannot be determined so
        the caller can skip the update instead of assuming a bogus value
        that would make every launch look out of date.
        """
        try:
            main_mod = sys.modules.get('__main__')
            if main_mod is not None and hasattr(main_mod, 'VERSION'):
                return str(main_mod.VERSION).strip()

            import main
            return str(main.VERSION).strip()
        except Exception as e:
            log(f"Error reading current version: {e}")
            return None
    
    def check_for_updates(self):
        """Check if updates are available."""
        try:
            # Get current version
            current_version = self.get_current_version()
            if not current_version:
                # We could not determine the installed version. Do NOT report
                # an update - otherwise an unknown local version would compare
                # unequal to the remote one and block startup forever.
                log("[UPDATER] Could not determine current version; skipping update check")
                return False, None, None

            # Get remote version.
            #
            # (connect, read), and short on purpose: this runs BEFORE Titan's
            # window exists, so every second it waits is a second of a
            # program that has been started and shows nothing at all.  A
            # server that has not answered in four seconds is a server that
            # is not going to tell us anything useful about a version, and
            # failing the check means starting normally - which is the right
            # answer for a machine that is offline or behind a captive
            # portal.  The DOWNLOAD keeps its long timeout; by then there is
            # a window and a progress dialog to wait in.
            response = requests.get(self.version_url,
                                    timeout=STARTUP_CHECK_TIMEOUT)
            response.raise_for_status()
            remote_version_raw = response.text.strip()

            if not remote_version_raw:
                log("[UPDATER] Empty remote version; skipping update check")
                return False, current_version, current_version

            # Check if version ends with 'i' (interpreter flag)
            if remote_version_raw.endswith('i'):
                self.needs_interpreter = True
                # Strip 'i' from version for display and comparison
                remote_version = remote_version_raw[:-1]
                log(f"[UPDATER] Version ends with 'i' - will download interpreter package")
                log(f"[UPDATER] Display version: {remote_version} (raw: {remote_version_raw})")
            else:
                self.needs_interpreter = False
                remote_version = remote_version_raw

            # Compare versions (without 'i' suffix)
            if remote_version != current_version:
                return True, current_version, remote_version
            else:
                return False, current_version, remote_version

        except Exception as e:
            log(f"Error checking for updates: {e}")
            return False, None, None
    
    def get_changes(self):
        """Get changelog from server."""
        try:
            response = requests.get(self.changes_url,
                                    timeout=STARTUP_CHECK_TIMEOUT)
            response.raise_for_status()
            return response.text
        except Exception as e:
            log(f"Error getting changelog: {e}")
            return _("Unable to retrieve changelog.")
    
    def show_update_dialog(self, current_version, new_version, changes):
        """Show update dialog to user."""
        dialog = UpdateDialog(self.parent, current_version, new_version, changes)
        result = dialog.ShowModal()
        dialog.Destroy()
        return result == wx.ID_OK
    
    def download_update(self, progress_dialog):
        """Download update file with progress reporting."""
        try:
            response = requests.get(self.download_url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(self.temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # Update progress
                        if total_size > 0:
                            progress = int((downloaded / total_size) * 100)
                            progress_dialog.update_progress(progress)
            
            return True
            
        except Exception as e:
            progress_dialog.update_progress(100, _("Download failed"))
            return self._fail(f"the update could not be downloaded from "
                              f"{self.download_url}: {e}")
    
    def _inside_install(self, path):
        """True when ``path`` lives inside the directory being updated."""
        try:
            a = os.path.normcase(os.path.abspath(path))
            root = os.path.normcase(os.path.abspath(self.install_dir))
            return a == root or a.startswith(root + os.sep)
        except Exception:
            return False

    def _resolve_extractor(self):
        """Return a 7-Zip that this update cannot pull out from under itself.

        Titan ships its own 7-Zip at ``data/bin/7z.exe`` (with ``7z.dll``
        beside it), and the update archive contains those two files like
        every other file in the install. So in a compiled build the
        sequence was:

          1. _stage_locked_targets() renames every file the archive will
             overwrite to ``<name>.old`` - INCLUDING ``data/bin/7z.exe``
             and ``data/bin/7z.dll``;
          2. the very next line launches ``data/bin/7z.exe``, which no
             longer exists.

        Measured on the real 0.6 archive: ``[WinError 2] The system cannot
        find the file specified``, caught by the broad ``except``, rolled
        straight back - so every single compiled update failed, always, and
        the user only ever saw "Update failed. Please try again later."

        The tool doing the work must therefore stand outside the tree it is
        rewriting: it is copied (with the DLLs it needs) into a private
        temporary directory once per update, and the copy is what runs.
        _release_extractor() removes it afterwards.
        """
        if self._extractor is not None:
            return self._extractor

        source = self.seven_zip_path
        if not os.path.exists(source):
            found = shutil.which('7z')
            if found:
                source = found

        if not os.path.exists(source) or not self._inside_install(source):
            # Either nothing to run (the caller reports that) or a 7-Zip the
            # archive does not contain - safe to use where it stands.
            self._extractor = source
            return self._extractor

        try:
            self._extractor_dir = tempfile.mkdtemp(prefix='titan_update_7z_')
            copy = os.path.join(self._extractor_dir, os.path.basename(source))
            shutil.copy2(source, copy)
            # 7z.exe cannot decode anything without 7z.dll next to it.
            src_dir = os.path.dirname(source)
            for name in os.listdir(src_dir):
                if name.lower().endswith('.dll'):
                    shutil.copy2(os.path.join(src_dir, name),
                                 os.path.join(self._extractor_dir, name))
            self._extractor = copy
            log(f"[UPDATER] Extracting with a private copy of 7-Zip: {copy}")
        except Exception as e:
            # Fall back to the in-tree one; _stage_locked_targets then leaves
            # it alone so it at least still exists when it is launched.
            log(f"Could not copy 7-Zip out of the install directory: {e}")
            self._extractor = source
        return self._extractor

    def _release_extractor(self):
        """Delete the temporary copy of 7-Zip made by _resolve_extractor."""
        directory, self._extractor_dir, self._extractor = self._extractor_dir, None, None
        if not directory:
            return
        try:
            shutil.rmtree(directory, ignore_errors=True)
        except Exception:
            pass

    def _archive_entries_py7zr(self, archive_path):
        """The archive's contents read in this process, or None.

        None means "ask 7-Zip instead" - it is not an error, only the answer
        that this machine has no py7zr.
        """
        try:
            import py7zr
        except Exception:
            return None
        try:
            with py7zr.SevenZipFile(archive_path, 'r') as archive:
                return [(item.filename, item.is_directory)
                        for item in archive.list()]
        except Exception as e:
            log(f"[UPDATER] py7zr could not read {archive_path}: {e}")
            return None

    def _list_archive_entries(self, archive_path):
        """Return the list of (relative_path, is_dir) contained in a 7z archive.

        Uses `7z l -slt`, whose ``Path = ...`` / ``Attributes = ...`` lines
        are parsed reliably even for names containing spaces. Only entries
        listed after the ``----------`` separator are real files - the block
        before it describes the archive itself.
        """
        entries = self._archive_entries_py7zr(archive_path)
        if entries is not None:
            return entries

        entries = []
        try:
            proc = subprocess.run(
                [self._resolve_extractor(), 'l', '-slt', '-sccUTF-8', archive_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=self.install_dir, **get_subprocess_kwargs()
            )
            text = proc.stdout.decode('utf-8', errors='replace')
        except Exception as e:
            log(f"Could not list archive {archive_path}: {e}")
            return entries

        in_files = False
        cur_path = None
        cur_attr = ''
        for line in text.splitlines():
            if not in_files:
                if line.strip().startswith('----------'):
                    in_files = True
                continue
            if line.startswith('Path = '):
                cur_path = line[len('Path = '):].strip()
                cur_attr = ''
            elif line.startswith('Attributes = '):
                cur_attr = line[len('Attributes = '):].strip()
            elif line.strip() == '' and cur_path is not None:
                entries.append((cur_path, 'D' in cur_attr))
                cur_path = None
                cur_attr = ''
        if cur_path is not None:
            entries.append((cur_path, 'D' in cur_attr))
        return entries

    def _stage_locked_targets(self, archive_path):
        """Rename existing files an archive will overwrite to ``<name>.old``.

        Titan ships compiled: while it runs, Windows locks the running
        ``Titan.exe`` and every loaded native module in ``_internal/``
        (``python3XX.dll``, ``*.pyd``, ``*.dll``), so 7-Zip cannot overwrite
        them in place. Windows DOES allow *renaming* a running exe / loaded
        DLL, which frees the original name for the fresh copy to be extracted
        into. The leftover ``.old`` files are removed at the next startup by
        cleanup_old_update_files() once the process no longer holds them.

        Returns a list of rollback records describing exactly what to undo if
        extraction later fails, so the running install can be restored bit for
        bit:

          ('rename', old_path, target) - existing file moved to <target>.old
          ('new', target, None)        - file the archive will create fresh

        Restoring a 'rename' removes the freshly-extracted file and renames
        the ``.old`` back; undoing a 'new' just deletes the created file - so
        rollback leaves neither a half-replaced nor a half-added install.
        """
        staged = []
        # Only relevant when an external 7-Zip is going to be run AND the
        # private copy of it could not be made, leaving us about to launch
        # Titan's own data/bin/7z.exe: moving THAT aside is what broke every
        # compiled update (see _resolve_extractor). Deliberately asks
        # self._extractor rather than resolving one - unpacking in-process
        # needs no external program and must not go looking for one.
        extractor = (os.path.normcase(os.path.abspath(self._extractor))
                     if self._extractor else None)
        extractor_dir = (os.path.dirname(extractor)
                         if extractor and self._inside_install(extractor)
                         else None)

        for rel, is_dir in self._list_archive_entries(archive_path):
            if is_dir:
                continue
            target = os.path.join(self.install_dir, rel.replace('/', os.sep))
            if extractor_dir is not None:
                norm = os.path.normcase(os.path.abspath(target))
                if norm == extractor or (os.path.dirname(norm) == extractor_dir
                                         and norm.endswith('.dll')):
                    # Leave the running extractor and its DLLs where they are.
                    continue
            if not os.path.exists(target):
                # Brand-new file. Nothing to move aside, but record it so a
                # rollback deletes it instead of leaving new-version orphans.
                staged.append(('new', target, None))
                continue

            old_path = target + '.old'
            try:
                if os.path.exists(old_path):
                    os.remove(old_path)  # stale leftover from a prior update
            except Exception:
                # Previous .old is somehow still held - use a unique name.
                old_path = target + '.old{}'.format(int(time.time() * 1000) % 100000)
            try:
                staged.append(self._move_aside(target, old_path))
            except Exception as e:
                # Neither renamed nor copied. Roll back what we staged so far
                # and abort staging so extraction doesn't half-replace.
                self._fail(f"{target} could not be moved aside: {e}")
                self._rollback_staging(staged)
                raise
        renamed = sum(1 for kind, _a, _b in staged if kind == 'rename')
        copied = sum(1 for kind, _a, _b in staged if kind == 'copied')
        new = sum(1 for kind, _a, _b in staged if kind == 'new')
        log(f"[UPDATER] staged {renamed} file(s) aside, {copied} copied aside "
            f"because they are in use, {new} new")
        return staged

    #: How many times a refused rename is tried again, and how long apart.
    MOVE_RETRIES = 3
    MOVE_RETRY_WAIT = 0.2

    def _move_aside(self, target, old_path):
        """Free ``target``'s name for the new copy; answer a rollback record.

        Windows lets a RUNNING executable and a LOADED library be renamed,
        which is what staging relies on. It does NOT let a file be renamed
        while any handle on it was opened without FILE_SHARE_DELETE - and an
        ordinary ``open()`` is exactly such a handle, so a file the running
        Titan merely has open for reading answers ``os.replace`` with
        ``[WinError 32]``. Measured. Staging used to raise on the first one
        and the whole update was rolled back and reported as "Update failed",
        with nothing to say which file.

        So a rename that is refused is tried again briefly (a scanner may be
        about to let go), and a file that stays in use is COPIED to its
        ``.old`` instead: Windows allows the copy, and the extractor then
        overwrites the original in place (a Python-style handle shares
        writing). If even that is refused, extraction fails and the rollback
        copies the ``.old`` back. The file is named in ``files_in_use`` and in
        the log either way.
        """
        error = None
        for attempt in range(1 + self.MOVE_RETRIES):
            try:
                os.replace(target, old_path)
                return ('rename', old_path, target)
            except OSError as e:
                error = e
                if attempt < self.MOVE_RETRIES:
                    time.sleep(self.MOVE_RETRY_WAIT)
        if not isinstance(self.files_in_use, list):
            self.files_in_use = []
        self.files_in_use.append(target)
        log(f"[UPDATER] {target} is in use ({error}); keeping a copy as "
            f"{os.path.basename(old_path)} and overwriting it in place")
        shutil.copy2(target, old_path)
        return ('copied', old_path, target)

    def _rollback_staging(self, staged):
        """Undo _stage_locked_targets: restore renamed files, drop new ones."""
        for record in staged:
            kind, a, b = record
            try:
                if kind == 'rename':
                    old_path, target = a, b
                    if os.path.exists(target):
                        # The partially-extracted new file is not the running
                        # image, so it can be removed; then restore the old one.
                        os.remove(target)
                    os.replace(old_path, target)
                elif kind == 'copied':
                    # The original was in use and was overwritten in place (or
                    # not reached); put its contents back from the copy.
                    old_path, target = a, b
                    shutil.copy2(old_path, target)
                    os.remove(old_path)
                elif kind == 'new':
                    target = a
                    if os.path.exists(target):
                        os.remove(target)  # created by the aborted extraction
            except Exception as e:
                if not isinstance(self.rollback_problems, list):
                    self.rollback_problems = []
                self.rollback_problems.append(f"{a}: {e}")
                log(f"[UPDATER] Rollback failed for {a}: {e}")
        if staged:
            log(f"[UPDATER] rolled back {len(staged)} staged file(s); "
                f"{len(self.rollback_problems)} could not be restored")

    def _py7zr_available(self):
        """Whether this Titan can unpack a 7z archive by itself."""
        try:
            import py7zr  # noqa: F401
            return True
        except Exception:
            return False

    def _py7zr_can_unpack(self, archive_path):
        """``(True, None)`` when py7zr can decode every block of this archive,
        ``(False, why)`` when it cannot.

        py7zr being importable says nothing about a particular archive. 7-Zip
        picks its filters per file: an ARM64 DLL in the tree (sounddevice
        ships two) goes into a block with the ARM64 branch filter, and py7zr
        has no decoder for it - ``UnsupportedCompressionMethodError`` from
        the middle of ``extractall``, after most of the install had already
        been written. Measured on the real titan.main.7z of 2026-10-02. The
        question is asked of the header alone, before a single file is
        touched: a decompressor is built for each block, which is where
        py7zr decides whether it knows the coders, and nothing is decoded.
        """
        try:
            import py7zr
            from py7zr.compressor import SevenZipDecompressor
        except Exception as e:
            return False, f"py7zr is not available ({e})"
        try:
            with py7zr.SevenZipFile(archive_path, 'r') as archive:
                folders = archive.header.main_streams.unpackinfo.folders
                for index, folder in enumerate(folders):
                    methods = ' '.join(_method_name(c) for c in folder.coders)
                    try:
                        SevenZipDecompressor(folder.coders, 1,
                                             list(folder.unpacksizes), 0, None)
                    except Exception as e:
                        return False, (f"py7zr cannot decode block {index} of "
                                       f"{len(folders)} ({methods}): {e}")
        except Exception as e:
            return False, f"py7zr could not read the archive: {e}"
        return True, None

    def _extract_with_py7zr(self, archive_path, progress_dialog, status_text,
                            exclude=()):
        """Unpack the archive in this process, with no 7-Zip at all.

        Preferred over ``data/bin/7z.exe`` because it removes the whole class
        of bug this file was rewritten for: there is no external program that
        the update can rename, replace or fail to find halfway through. It
        also means an installation whose ``data/bin`` is missing or damaged
        can still update itself.

        Measured on the real 236 MB titan.main.7z: 28.2 s against 14.6 s for
        7z.exe, producing a byte-identical tree (7 786 files, no size
        differing). Twice as long, on an update that has just spent minutes
        downloading, in exchange for not depending on a file inside the
        directory being rewritten - which is the trade this is worth.

        Returns True on success, False when py7zr is not available or cannot
        read the archive, in which case the caller falls back to 7-Zip.
        """
        try:
            import py7zr
        except Exception:
            return False

        class Report(py7zr.callbacks.ExtractCallback):
            """py7zr reports files; the dialog wants a percentage."""

            def __init__(self, total, report):
                self.total = max(1, total)
                self.done = 0
                self.last = -1
                self.report = report

            def report_start_preparation(self):
                pass

            def report_start(self, processing_file_path, processing_bytes):
                pass

            def report_update(self, decompressed_bytes):
                pass

            def report_end(self, processing_file_path, wrote_bytes):
                self.done += 1
                percent = min(99, int(self.done * 100 / self.total))
                if percent != self.last:
                    self.last = percent
                    self.report(percent)

            def report_postprocess(self):
                pass

            def report_warning(self, message):
                log(f"[UPDATER] py7zr: {message}")

        def report(percent):
            progress_dialog.update_progress(
                percent, _("Extracting files... {}%").format(percent))

        try:
            with py7zr.SevenZipFile(archive_path, 'r') as archive:
                names = archive.getnames()
                total = len(names)
                archive.reset()
                if exclude:
                    # Files in use are written over afterwards
                    # (_replace_files_in_use), not here.
                    skip = {self._relative(t) for t in exclude}
                    wanted = [n for n in names if n.replace('\\', '/') not in skip]
                    archive.extract(path=self.install_dir, targets=wanted,
                                    callback=Report(total, report))
                else:
                    archive.extractall(path=self.install_dir,
                                       callback=Report(total, report))
        except Exception as e:
            self._fail(f"py7zr could not unpack {archive_path}: "
                       f"{type(e).__name__}: {e}")
            return False

        progress_dialog.update_progress(100, _("Extraction complete"))
        return True

    def _extract_archive(self, archive_path, progress_dialog, status_text,
                         staged=None):
        """Extract a 7z archive with real progress reporting.

        Reads 7z stdout to prevent pipe buffer deadlock and parses
        progress percentage from -bsp1 output. In a compiled build the files
        that would be overwritten may be locked, so they are first renamed to
        ``.old`` (see _stage_locked_targets).

        Staging/rollback ownership depends on ``staged``:

        - ``staged is None`` (single-package update): this call owns staging
          and rolls it back itself if extraction fails.
        - a caller-provided list (multi-package update): the rename pairs are
          appended to that shared list and this method does NOT roll back on
          failure - the caller rolls back the whole set so, e.g., a failed
          interpreter extraction also undoes the already-extracted program.
        """
        own_staging = staged is None
        if own_staging:
            staged = []
        try:
            progress_dialog.update_progress(0, status_text)

            if not os.path.exists(archive_path):
                return self._fail(f"the archive to extract does not exist: "
                                  f"{archive_path}")

            # Who unpacks this is decided BEFORE anything is moved aside, and
            # per ARCHIVE: py7zr being importable is not py7zr being able to
            # decode this one (see _py7zr_can_unpack).
            in_process, why_not = self._py7zr_can_unpack(archive_path)

            # The external 7-Zip is secured FIRST, whichever extractor is
            # going to be used - copied out of the install into a private
            # directory. Resolving it only when py7zr had already failed is
            # what made the fallback a lie: by then staging had renamed
            # data/bin/7z.exe to 7z.exe.old, and the update went on only on
            # a machine that happened to have a 7-Zip on PATH.
            seven_zip = self._resolve_extractor()
            have_seven_zip = bool(seven_zip) and os.path.exists(seven_zip)
            if not in_process:
                if not have_seven_zip:
                    # Nothing can unpack this here. Said before a single file
                    # has been touched, with both reasons.
                    return self._fail(
                        f"{why_not}; and there is no 7-Zip to fall back on "
                        f"(looked at {self.seven_zip_path} and on PATH)")
                log(f"[UPDATER] {why_not}; unpacking with 7-Zip instead")
            else:
                log(f"[UPDATER] unpacking in-process with py7zr"
                    + (f"; 7-Zip ready as a fallback at {seven_zip}"
                       if have_seven_zip else "; no 7-Zip to fall back on"))

            # Compiled build: move locked targets (running exe, loaded DLLs)
            # aside so the new copies can be written. Windows does allow a
            # running .exe and a loaded .dll to be RENAMED, which is what
            # frees the name. Dev build has nothing locked, so plain
            # overwrite is enough.
            if is_frozen():
                staged.extend(self._stage_locked_targets(archive_path))

            # Unpack in this process when we can: no external program means
            # nothing for the update to rename out from under itself, and an
            # install whose data/bin is damaged can still be repaired.
            # Files the running program holds open: neither extractor
            # replaces them directly (see _move_aside / _replace_files_in_use).
            in_use = [target for kind, _old, target in staged
                      if kind == 'copied']

            if in_process:
                if self._extract_with_py7zr(archive_path, progress_dialog,
                                            status_text, exclude=in_use):
                    if in_use and not self._replace_files_in_use(
                            archive_path, in_use,
                            seven_zip if have_seven_zip else None):
                        if own_staging:
                            self._rollback_staging(staged)
                        return False
                    return True
                # It could be read and still failed part way through. 7-Zip
                # is the second opinion; -aoa overwrites whatever py7zr left.
                if not have_seven_zip:
                    self._fail(f"{self.failure_reason}; and there is no 7-Zip "
                               f"to fall back on")
                    if own_staging:
                        self._rollback_staging(staged)
                    return False
                log(f"[UPDATER] falling back to 7-Zip at {seven_zip}")

            # -bsp1 outputs progress percentage to stdout
            # -aoa forces overwrite of ALL existing files (without it a stale
            #      file already on disk can be silently kept, leaving a
            #      half-updated install).
            # -sccUTF-8 makes its messages readable in the log whatever the
            #      console code page is.
            # Extract to the install dir explicitly so cwd cannot affect us.
            cmd = [
                seven_zip, 'x', archive_path, '-y', '-aoa', '-sccUTF-8',
                f'-o{self.install_dir}', '-bsp1'
            ]
            # A file in use cannot be replaced by 7-Zip, which deletes the
            # old file before writing the new one: it is left out here and
            # written over afterwards (_replace_files_in_use).
            exclude_list = None
            if in_use:
                exclude_list = self._write_list_file(in_use)
                cmd.append(f'-x@{exclude_list}')

            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=self.install_dir,
                **get_subprocess_kwargs()
            )

            # Drain stderr in background thread to prevent pipe buffer deadlock
            stderr_chunks = []
            def drain_stderr():
                try:
                    data = process.stderr.read()
                    if data:
                        stderr_chunks.append(data)
                except Exception:
                    pass
            stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
            stderr_thread.start()

            # Read stdout and parse progress (7z uses \r for progress lines)
            buf = b''
            last_percent = -1
            while True:
                chunk = process.stdout.read(512)
                if not chunk:
                    break
                buf += chunk

                # Split on \r or \n to find complete lines
                while True:
                    r_pos = buf.find(b'\r')
                    n_pos = buf.find(b'\n')
                    if r_pos == -1 and n_pos == -1:
                        break
                    if r_pos == -1:
                        r_pos = len(buf) + 1
                    if n_pos == -1:
                        n_pos = len(buf) + 1
                    pos = min(r_pos, n_pos)
                    line = buf[:pos].decode('utf-8', errors='replace').strip()
                    buf = buf[pos + 1:]

                    if line:
                        match = re.match(r'(\d+)%', line)
                        if match:
                            percent = int(match.group(1))
                            if percent != last_percent:
                                last_percent = percent
                                progress_dialog.update_progress(
                                    percent,
                                    _("Extracting files... {}%").format(percent)
                                )

            returncode = process.wait()
            stderr_thread.join(timeout=5)
            if exclude_list:
                try:
                    os.remove(exclude_list)
                except OSError:
                    pass

            if returncode == 0 and in_use:
                progress_dialog.update_progress(
                    99, _("Replacing files that are in use..."))
                if not self._replace_files_in_use(archive_path, in_use,
                                                  seven_zip):
                    if own_staging:
                        self._rollback_staging(staged)
                    return False

            if returncode == 0:
                progress_dialog.update_progress(100, _("Extraction complete"))
                return True
            else:
                stderr_text = b''.join(stderr_chunks).decode('utf-8', errors='replace') if stderr_chunks else ''
                self._fail(f"7-Zip exited with code {returncode} unpacking "
                           f"{archive_path}: {stderr_text.strip()[:600]}")
                # Extraction failed. If we own staging, restore the files we
                # moved aside so the running (old) install stays intact.
                # Otherwise the caller rolls back the whole multi-package set.
                if own_staging:
                    self._rollback_staging(staged)
                return False

        except Exception as e:
            log(traceback.format_exc())
            self._fail(f"extracting {archive_path} raised "
                       f"{type(e).__name__}: {e}")
            if own_staging:
                self._rollback_staging(staged)
            return False
        finally:
            self._remove_archive(archive_path)

    def _relative(self, target):
        """``target`` as the archive names it (forward slashes, no root)."""
        rel = os.path.relpath(target, self.install_dir)
        return rel.replace(os.sep, '/')

    def _write_list_file(self, targets):
        """A 7-Zip list file (``-x@``/``-i@``) naming these install files."""
        handle = tempfile.NamedTemporaryFile('w', suffix='.lst', delete=False,
                                             encoding='utf-8-sig')
        with handle:
            for target in targets:
                handle.write(self._relative(target) + '\n')
        return handle.name

    def _unpack_some(self, archive_path, targets, side, seven_zip):
        """Unpack just ``targets`` into ``side``, with 7-Zip or py7zr."""
        if seven_zip:
            include_list = self._write_list_file(targets)
            try:
                proc = subprocess.run(
                    [seven_zip, 'x', archive_path, '-y', '-aoa', '-sccUTF-8',
                     f'-o{side}', f'-i@{include_list}'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=self.install_dir, **get_subprocess_kwargs())
            finally:
                try:
                    os.remove(include_list)
                except OSError:
                    pass
            if proc.returncode != 0:
                err = proc.stderr.decode('utf-8', errors='replace').strip()
                return self._fail(f"7-Zip could not unpack the files in use "
                                  f"(code {proc.returncode}): {err[:600]}")
            return True
        try:
            import py7zr
            with py7zr.SevenZipFile(archive_path, 'r') as archive:
                archive.extract(path=side,
                                targets=[self._relative(t) for t in targets])
            return True
        except Exception as e:
            return self._fail(f"py7zr could not unpack the files in use: "
                              f"{type(e).__name__}: {e}")

    def _replace_files_in_use(self, archive_path, targets, seven_zip=None):
        """Write the new contents over files another handle holds open.

        Measured in the frozen build: the running Titan itself holds
        ``_internal/base_library.zip`` open (zipimport keeps the standard
        library's archive open for the life of the process), so this is
        reached on EVERY compiled update, not only when some other program
        is in the way. That file is usually byte-identical between two
        builds of the same Python, and a file that would not change is left
        exactly alone: writing over an archive the process is still reading
        from is what a stale central directory and a failed import at exit
        look like.

        7-Zip replaces a file by deleting it first, which Windows refuses for
        a file that is open; a plain write does not delete and is allowed for
        the sharing an ordinary open() grants. So these few files are
        unpacked into a private directory and copied over their originals.
        A holder that shares nothing makes the copy fail, and that failure
        names the file.
        """
        side = tempfile.mkdtemp(prefix='titan_update_inuse_')
        try:
            if not self._unpack_some(archive_path, targets, side, seven_zip):
                return False
            for target in targets:
                fresh = os.path.join(side, self._relative(target)
                                     .replace('/', os.sep))
                if not os.path.exists(fresh):
                    return self._fail(f"{self._relative(target)} is not in "
                                      f"the archive after all")
                try:
                    if filecmp.cmp(fresh, target, shallow=False):
                        log(f"[UPDATER] {target} is in use and unchanged by "
                            f"this update; left alone")
                        continue
                except OSError:
                    pass
                try:
                    shutil.copyfile(fresh, target)
                except OSError as e:
                    return self._fail(
                        f"{target} is in use by another program and could "
                        f"not be written over: {e}")
                log(f"[UPDATER] wrote over {target} while it is in use")
            return True
        finally:
            shutil.rmtree(side, ignore_errors=True)

    def _remove_archive(self, archive_path, attempts=5):
        """Delete a downloaded archive, allowing a scanner a moment to let go.

        A 300 MB file that has just been written is exactly what an antivirus
        scanner opens, and os.remove answers that with [WinError 32]. A
        leftover archive is not a failed update, so this never raises.
        """
        for attempt in range(attempts):
            try:
                if os.path.exists(archive_path):
                    os.remove(archive_path)
                return
            except Exception as e:
                if attempt == attempts - 1:
                    log(f"[UPDATER] could not remove {archive_path}: {e}")
                else:
                    time.sleep(0.5)

    def extract_update(self, progress_dialog, staged=None):
        """Extract update using 7zip.

        ``staged`` is forwarded to _extract_archive: pass a shared list to
        make this part of a multi-package update whose rollback is owned by
        the caller.
        """
        return self._extract_archive(
            self.temp_file, progress_dialog, _("Extracting update..."),
            staged=staged
        )

    def download_interpreter(self, progress_dialog):
        """Download interpreter package with progress reporting."""
        try:
            progress_dialog.update_progress(0, _("Downloading Python interpreter..."))

            response = requests.get(self.interpreter_url, stream=True, timeout=30)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(self.temp_interpreter_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        # Update progress
                        if total_size > 0:
                            progress = int((downloaded / total_size) * 100)
                            progress_dialog.update_progress(progress, _("Downloading Python interpreter..."))

            log(f"[UPDATER] Interpreter downloaded successfully")
            return True

        except Exception as e:
            progress_dialog.update_progress(100, _("Interpreter download failed"))
            return self._fail(f"the interpreter could not be downloaded from "
                              f"{self.interpreter_url}: {e}")

    def extract_interpreter(self, progress_dialog, staged=None):
        """Extract interpreter package using 7zip.

        Reuses _extract_archive so we get the same pipe draining and
        progress parsing as the main update extraction. Without draining
        the pipes the 7z subprocess can deadlock when its progress output
        fills the OS pipe buffer. ``staged`` is forwarded so the interpreter
        can share the program's rollback set in a combined update.
        """
        return self._extract_archive(
            self.temp_interpreter_file, progress_dialog,
            _("Extracting Python interpreter..."), staged=staged
        )

    def _run_update_steps(self, progress_dialog):
        """Run the download/extract steps. Returns True on success.

        Runs on a worker thread. When an interpreter update is required the
        program AND the interpreter are downloaded together first, and only
        then extracted together ("na raz"). The two extractions share ONE
        rollback set, so if either the program or the interpreter fails to
        extract, BOTH are rolled back and the running install is left exactly
        as it was - never a mismatched, half-updated mix of new program with
        old interpreter (or vice versa). Every step short-circuits.
        """
        if self.needs_interpreter:
            # Download both packages before touching the install.
            if not self.download_update(progress_dialog):
                return False
            if not self.download_interpreter(progress_dialog):
                return False

            # Both archives are on disk. Extract them under a single shared
            # rollback set so any failure undoes the whole pair. Rolling back
            # a staged rename removes the freshly-extracted file and restores
            # the ``.old`` original, so even an already-extracted program is
            # reverted when the interpreter step fails.
            staged = []
            if not self.extract_update(progress_dialog, staged=staged):
                self._rollback_staging(staged)
                return False
            if not self.extract_interpreter(progress_dialog, staged=staged):
                self._rollback_staging(staged)
                return False
            return True

        # Program-only update: _extract_archive manages its own rollback.
        if not self.download_update(progress_dialog):
            return False
        if not self.extract_update(progress_dialog):
            return False
        return True

    def perform_update(self, steps=None):
        """Perform the full update process, BLOCKING until it finishes.

        ``steps`` is the work to do on the worker thread, given the progress
        dialog and answering True on success; it defaults to the download
        and extraction of the published update (_run_update_steps). apply_local
        passes the steps for an archive already on the disk.

        The old implementation started a worker thread and returned True
        immediately, so the caller (startup code) went on to build and show
        the whole Titan suite while the download/extraction was still
        running in the background - and, worse, before the wx main loop was
        even running, so the queued completion callback never fired
        predictably.

        Here we still do the network/CPU work on a worker thread (so the UI
        stays responsive and the progress bar updates), but we pump the
        event loop with wx.YieldIfNeeded() until the worker is done and then
        return the real success/failure. That guarantees the suite does not
        continue starting until the update is fully applied.
        """
        if steps is None:
            steps = self._run_update_steps
        self.failure_reason = None
        self.files_in_use = []
        self.rollback_problems = []
        self._log_environment()
        progress_dialog = None
        try:
            progress_dialog = ProgressDialog(self.parent)
            progress_dialog.Show()

            done_event = threading.Event()
            result = {'success': False}

            def update_thread():
                try:
                    result['success'] = steps(progress_dialog)
                except Exception as e:
                    log(traceback.format_exc())
                    self._fail(f"the update thread raised "
                               f"{type(e).__name__}: {e}")
                    result['success'] = False
                finally:
                    done_event.set()
                    # Nudge the (possibly idle) event loop so the wait below
                    # wakes up promptly once the worker finishes.
                    wx.CallAfter(lambda: None)

            thread = threading.Thread(target=update_thread, daemon=True)
            thread.start()

            # Block here - but keep the UI alive - until the update is done.
            while not done_event.is_set():
                wx.YieldIfNeeded()
                time.sleep(0.02)
            # Flush any last progress updates queued via wx.CallAfter.
            wx.YieldIfNeeded()

            if result['success']:
                self.failure_reason = None
                log("[UPDATER] update applied successfully")
            else:
                log(f"[UPDATER] update failed: {self.failure_reason}")
            return bool(result['success'])

        except Exception as e:
            log(traceback.format_exc())
            self._fail(f"performing the update raised {type(e).__name__}: {e}")
            return False
        finally:
            self._release_extractor()
            if progress_dialog is not None:
                try:
                    progress_dialog.Destroy()
                except Exception:
                    pass

    def failure_message(self):
        """The sentences the failure dialog shows.

        "Update failed. Please try again later." was the whole of it, for
        every failure there is, and it sent the user to try again something
        that would fail the same way. Now: whether the installation was left
        as it was, WHY it failed, and where the full log is.
        """
        lines = [_("Update failed. Please try again later.")]
        if self.rollback_problems:
            lines.append(_("Some files could not be put back; see the log."))
        else:
            lines.append(_("The installation was left as it was."))
        if self.failure_reason:
            lines.append(_("Reason: {}").format(self.failure_reason))
        if self.files_in_use:
            shown = self.files_in_use[:5]
            more = len(self.files_in_use) - len(shown)
            names = ', '.join(os.path.relpath(f, self.install_dir)
                              for f in shown)
            if more > 0:
                names += ' ' + _("and {} more").format(more)
            lines.append(_("Files in use by a running program: {}")
                         .format(names))
        lines.append(_("Details were written to {}").format(log_path()))
        return '\n\n'.join(lines)

    def _show_result(self, success):
        """Show the final success/failure message to the user."""
        if success:
            dlg = wx.MessageDialog(
                self.parent,
                _("Update completed successfully! Please restart the application."),
                _("Update Complete"),
                wx.OK | wx.ICON_INFORMATION,
            )
            _apply_skin_to_tree(dlg)
            dlg.ShowModal()
            dlg.Destroy()
        else:
            dlg = wx.MessageDialog(
                self.parent,
                self.failure_message(),
                _("Update Error"),
                wx.OK | wx.ICON_ERROR,
            )
            _apply_skin_to_tree(dlg)
            dlg.ShowModal()
            dlg.Destroy()

    # ------------------------------------------------------------ local file

    def _apply_local_steps(self, progress_dialog, archive_path,
                           interpreter_path=None):
        """The steps for an archive already on the disk (see apply_local)."""
        archives = [(archive_path, self.temp_file, _("Extracting update..."))]
        if interpreter_path:
            archives.append((interpreter_path, self.temp_interpreter_file,
                             _("Extracting Python interpreter...")))
        for source, target, _status in archives:
            if not os.path.exists(source):
                return self._fail(f"there is no such archive: {source}")
            progress_dialog.update_progress(0, _("Copying archive..."))
            log(f"[UPDATER] applying local archive {source}")
            # The extractor deletes the archive it was given; the user's
            # file is theirs, so it is a copy that is unpacked.
            if os.path.normcase(os.path.abspath(source)) != \
                    os.path.normcase(os.path.abspath(target)):
                shutil.copy2(source, target)

        if interpreter_path:
            staged = []
            if not self.extract_update(progress_dialog, staged=staged):
                self._rollback_staging(staged)
                return False
            if not self.extract_interpreter(progress_dialog, staged=staged):
                self._rollback_staging(staged)
                return False
            return True
        return self.extract_update(progress_dialog)

    def apply_local(self, archive_path, interpreter_path=None, show=True):
        """Apply a titan.main.7z (and optionally an interpreter archive)
        from the disk, through exactly the path the startup update takes.

        ``Titan.exe --apply-update <archive>`` is this. It exists for two
        reasons: an installation whose updater fails can be updated from an
        archive fetched by hand, and the compiled build can be made to update
        ITSELF on demand - which is the only way to see what the frozen
        process really does (the running exe, the loaded DLLs, the bundled
        py7zr, the inherited PATH), since the version check offers nothing to
        a build that is already current. Returns True on success.
        """
        log(f"[UPDATER] --apply-update {archive_path}"
            + (f" + {interpreter_path}" if interpreter_path else ""))
        success = self.perform_update(
            lambda dialog: self._apply_local_steps(dialog, archive_path,
                                                   interpreter_path))
        if show:
            self._show_result(success)
        return success


def exit_after_update(code=0):
    """Leave the process the moment an update has been applied.

    The files under the running process are the NEW version now - Titan.exe
    with its PYZ, the libraries - and interpreter finalisation imports and
    runs things (atexit handlers, threading's shutdown) out of them at the
    old offsets. Measured: a successful --apply-update exited 120 that way.
    Nothing needs tidying at this point - no window has been built - so the
    process ends here, with the log flushed.
    """
    try:
        sys.stdout and sys.stdout.flush()
        sys.stderr and sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)

    def check_and_update(self):
        """Check for updates and, if one exists, offer it before startup.

        Returns True ONLY when the Titan suite must NOT continue starting -
        i.e. an update was applied and the app has to restart into the new
        version. In every other case it returns False so the currently
        installed ("old") version launches normally:

          - no update available                    -> start normally  -> False
          - user cancels the update                -> start old version -> False
          - user updates, but it fails/rolls back  -> start old version -> False
          - user updates and it succeeds           -> restart needed   -> True

        The important guarantee (blocking startup while the download and
        extraction run) is provided by perform_update(), which does not
        return until the update is fully applied - so the suite never boots
        on top of a half-written install.
        """
        has_update, current_version, new_version = self.check_for_updates()

        if not has_update:
            return False

        log(f"[UPDATER] update offered: {current_version} -> {new_version}"
            f"{' with interpreter' if self.needs_interpreter else ''}")
        changes = self.get_changes()

        if not self.show_update_dialog(current_version, new_version, changes):
            # User declined - launch the current version as-is.
            log("[UPDATER] Update declined by user; starting current version")
            return False

        success = self.perform_update()
        self._show_result(success)

        if success:
            # New version is in place; the running process must restart.
            return True

        # Update failed and was rolled back - keep running the old version.
        log("[UPDATER] Update failed; starting current version")
        return False


def cleanup_old_update_files(base_dir=None):
    """Delete ``*.old`` files left behind by a previous in-place update.

    _stage_locked_targets() renames the running executable and any loaded
    native libraries to ``<name>.old`` so the new copies can be extracted
    over their original names. Those ``.old`` files cannot be removed while
    the old process still holds them, so cleanup happens here at the next
    startup - but only for a ``.old`` file whose live counterpart exists
    (proof it was a staged replacement), to avoid touching unrelated user
    files that merely end in ``.old``.
    """
    if base_dir is None:
        base_dir = get_base_path()

    removed = 0
    try:
        for root, dirs, files in os.walk(base_dir):
            # Skip the transient package cache; it manages its own lifetime.
            if 'pkg_cache' in dirs:
                dirs.remove('pkg_cache')
            for name in files:
                if not name.endswith('.old'):
                    continue
                old_path = os.path.join(root, name)
                live_path = old_path[:-len('.old')]
                if not os.path.exists(live_path):
                    continue  # not one of ours - leave it alone
                try:
                    os.remove(old_path)
                    removed += 1
                except Exception:
                    # Still locked (should not happen post-restart) - it will
                    # be retried on the next launch.
                    pass
    except Exception as e:
        log(f"Error cleaning up .old update files: {e}")

    if removed:
        log(f"[UPDATER] Removed {removed} leftover .old file(s) from previous update")


def check_for_updates_on_startup(parent=None):
    """Check for updates at startup.

    Returns True when the caller must stop and NOT continue launching the
    Titan suite (an update was applied and a restart is required). Returns
    False when startup should proceed normally with the current version.
    """
    # Always sweep leftovers from a prior in-place update first, whatever the
    # outcome of this check.
    cleanup_old_update_files()

    updater = Updater(parent)
    return updater.check_and_update()


if __name__ == "__main__":
    # Test the updater
    app = wx.App()
    
    updater = Updater()
    updater.check_and_update()
    
    app.MainLoop()