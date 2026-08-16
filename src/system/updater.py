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
from src.titan_core.sound import play_sound, play_focus_sound, play_select_sound
from src.titan_core.translation import _
from src.platform_utils import get_subprocess_kwargs, get_base_path, is_frozen, IS_WINDOWS
from src.titan_core.skin_manager import apply_skin_to_window


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
            print(f"Error reading current version: {e}")
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
                print("[UPDATER] Could not determine current version; skipping update check")
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
                print("[UPDATER] Empty remote version; skipping update check")
                return False, current_version, current_version

            # Check if version ends with 'i' (interpreter flag)
            if remote_version_raw.endswith('i'):
                self.needs_interpreter = True
                # Strip 'i' from version for display and comparison
                remote_version = remote_version_raw[:-1]
                print(f"[UPDATER] Version ends with 'i' - will download interpreter package")
                print(f"[UPDATER] Display version: {remote_version} (raw: {remote_version_raw})")
            else:
                self.needs_interpreter = False
                remote_version = remote_version_raw

            # Compare versions (without 'i' suffix)
            if remote_version != current_version:
                return True, current_version, remote_version
            else:
                return False, current_version, remote_version

        except Exception as e:
            print(f"Error checking for updates: {e}")
            return False, None, None
    
    def get_changes(self):
        """Get changelog from server."""
        try:
            response = requests.get(self.changes_url,
                                    timeout=STARTUP_CHECK_TIMEOUT)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"Error getting changelog: {e}")
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
            print(f"Error downloading update: {e}")
            progress_dialog.update_progress(100, _("Download failed"))
            return False
    
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
            print(f"[UPDATER] Extracting with a private copy of 7-Zip: {copy}")
        except Exception as e:
            # Fall back to the in-tree one; _stage_locked_targets then leaves
            # it alone so it at least still exists when it is launched.
            print(f"Could not copy 7-Zip out of the install directory: {e}")
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
            print(f"[UPDATER] py7zr could not read {archive_path}: {e}")
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
                [self._resolve_extractor(), 'l', '-slt', archive_path],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=self.install_dir, **get_subprocess_kwargs()
            )
            text = proc.stdout.decode('utf-8', errors='replace')
        except Exception as e:
            print(f"Could not list archive {archive_path}: {e}")
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
        # Only relevant when the private copy could not be made and we are
        # running Titan's own data/bin/7z.exe: moving THAT aside is what
        # broke every compiled update (see _resolve_extractor).
        extractor = os.path.normcase(os.path.abspath(self._resolve_extractor()))
        extractor_dir = (os.path.dirname(extractor)
                         if self._inside_install(extractor) else None)

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
                os.replace(target, old_path)
                staged.append(('rename', old_path, target))
            except Exception as e:
                # Renaming failed (unexpected). Roll back what we staged so
                # far and abort staging so extraction doesn't half-replace.
                print(f"Could not stage locked file {target}: {e}")
                self._rollback_staging(staged)
                raise
        return staged

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
                elif kind == 'new':
                    target = a
                    if os.path.exists(target):
                        os.remove(target)  # created by the aborted extraction
            except Exception as e:
                print(f"Rollback failed for {a}: {e}")

    def _extract_with_py7zr(self, archive_path, progress_dialog, status_text):
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
                print(f"[UPDATER] py7zr: {message}")

        def report(percent):
            progress_dialog.update_progress(
                percent, _("Extracting files... {}%").format(percent))

        try:
            with py7zr.SevenZipFile(archive_path, 'r') as archive:
                total = len(archive.getnames())
                archive.reset()
                archive.extractall(path=self.install_dir,
                                   callback=Report(total, report))
        except Exception as e:
            print(f"[UPDATER] py7zr could not unpack {archive_path}: {e}")
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
                print(f"Archive to extract does not exist: {archive_path}")
                return False

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
            if self._extract_with_py7zr(archive_path, progress_dialog,
                                        status_text):
                return True

            seven_zip = self._resolve_extractor()
            if not os.path.exists(seven_zip):
                print(f"7zip not found at {seven_zip}")
                if own_staging:
                    self._rollback_staging(staged)
                return False

            # -bsp1 outputs progress percentage to stdout
            # -aoa forces overwrite of ALL existing files (without it a stale
            #      file already on disk can be silently kept, leaving a
            #      half-updated install).
            # Extract to the install dir explicitly so cwd cannot affect us.
            cmd = [
                seven_zip, 'x', archive_path, '-y', '-aoa',
                f'-o{self.install_dir}', '-bsp1'
            ]

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

            if returncode == 0:
                progress_dialog.update_progress(100, _("Extraction complete"))
                return True
            else:
                stderr_text = b''.join(stderr_chunks).decode('utf-8', errors='replace') if stderr_chunks else ''
                print(f"7zip extraction failed with code {returncode}: {stderr_text}")
                # Extraction failed. If we own staging, restore the files we
                # moved aside so the running (old) install stays intact.
                # Otherwise the caller rolls back the whole multi-package set.
                if own_staging:
                    self._rollback_staging(staged)
                return False

        except Exception as e:
            print(f"Error extracting archive {archive_path}: {e}")
            if own_staging:
                self._rollback_staging(staged)
            return False
        finally:
            try:
                if os.path.exists(archive_path):
                    os.remove(archive_path)
            except Exception as e:
                print(f"Error cleaning up {archive_path}: {e}")

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

            print(f"[UPDATER] Interpreter downloaded successfully")
            return True

        except Exception as e:
            print(f"Error downloading interpreter: {e}")
            progress_dialog.update_progress(100, _("Interpreter download failed"))
            return False

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

    def perform_update(self):
        """Perform the full update process, BLOCKING until it finishes.

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
        progress_dialog = None
        try:
            progress_dialog = ProgressDialog(self.parent)
            progress_dialog.Show()

            done_event = threading.Event()
            result = {'success': False}

            def update_thread():
                try:
                    result['success'] = self._run_update_steps(progress_dialog)
                except Exception as e:
                    print(f"Update thread error: {e}")
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

            return bool(result['success'])

        except Exception as e:
            print(f"Error performing update: {e}")
            return False
        finally:
            self._release_extractor()
            if progress_dialog is not None:
                try:
                    progress_dialog.Destroy()
                except Exception:
                    pass

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
                _("Update failed. Please try again later."),
                _("Update Error"),
                wx.OK | wx.ICON_ERROR,
            )
            _apply_skin_to_tree(dlg)
            dlg.ShowModal()
            dlg.Destroy()

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

        changes = self.get_changes()

        if not self.show_update_dialog(current_version, new_version, changes):
            # User declined - launch the current version as-is.
            print("[UPDATER] Update declined by user; starting current version")
            return False

        success = self.perform_update()
        self._show_result(success)

        if success:
            # New version is in place; the running process must restart.
            return True

        # Update failed and was rolled back - keep running the old version.
        print("[UPDATER] Update failed; starting current version")
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
        print(f"Error cleaning up .old update files: {e}")

    if removed:
        print(f"[UPDATER] Removed {removed} leftover .old file(s) from previous update")


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