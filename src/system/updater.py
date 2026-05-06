import wx
import threading
import time
import requests
import os
import sys
import subprocess
import shutil
import re
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
        self.progress_bar.SetValue(progress)
        if status_text:
            self.status_label.SetLabel(status_text)


class Updater:
    def __init__(self, parent=None):
        self.parent = parent
        self.version_url = "https://titosofttitan.com/titan/titanchk/version.ver"
        self.changes_url = "https://titosofttitan.com/titan/titanchk/changes.txt"
        self.download_url = "https://titosofttitan.com/titan/titan.main.7z"
        self.interpreter_url = "https://titosofttitan.com/titan/titan.interpreter.7z"

        # Resolve install dir so the updater works regardless of cwd.
        # In compiled mode this is the directory containing TCE Launcher.exe;
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

        self.needs_interpreter = False  # Will be set if version ends with 'i'
    
    def get_current_version(self):
        """Get current program version from main.py."""
        try:
            # Import main module to get VERSION variable
            import main
            return main.VERSION
        except Exception as e:
            print(f"Error reading version from main.py: {e}")
            return "1.0.0"
    
    def check_for_updates(self):
        """Check if updates are available."""
        try:
            # Get current version
            current_version = self.get_current_version()

            # Get remote version
            response = requests.get(self.version_url, timeout=10)
            response.raise_for_status()
            remote_version_raw = response.text.strip()

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
            response = requests.get(self.changes_url, timeout=10)
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
    
    def _extract_archive(self, archive_path, progress_dialog, status_text):
        """Extract a 7z archive with real progress reporting.

        Reads 7z stdout to prevent pipe buffer deadlock and parses
        progress percentage from -bsp1 output.
        """
        try:
            progress_dialog.update_progress(0, status_text)

            if not os.path.exists(self.seven_zip_path):
                print(f"7zip not found at {self.seven_zip_path}")
                return False

            # -bsp1 outputs progress percentage to stdout
            # Extract to the install dir explicitly so cwd cannot affect us.
            cmd = [
                self.seven_zip_path, 'x', archive_path, '-y',
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
                return False

        except Exception as e:
            print(f"Error extracting archive {archive_path}: {e}")
            return False
        finally:
            try:
                if os.path.exists(archive_path):
                    os.remove(archive_path)
            except Exception as e:
                print(f"Error cleaning up {archive_path}: {e}")

    def extract_update(self, progress_dialog):
        """Extract update using 7zip."""
        return self._extract_archive(
            self.temp_file, progress_dialog, _("Extracting update...")
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

    def extract_interpreter(self, progress_dialog):
        """Extract interpreter package using 7zip.

        Reuses _extract_archive so we get the same pipe draining and
        progress parsing as the main update extraction. Without draining
        the pipes the 7z subprocess can deadlock when its progress output
        fills the OS pipe buffer.
        """
        return self._extract_archive(
            self.temp_interpreter_file, progress_dialog,
            _("Extracting Python interpreter...")
        )
    
    def perform_update(self):
        """Perform the full update process."""
        try:
            # Show progress dialog
            progress_dialog = ProgressDialog(self.parent)
            progress_dialog.Show()

            def update_thread():
                try:
                    # Download main update
                    if self.download_update(progress_dialog):
                        # Extract main update
                        if self.extract_update(progress_dialog):
                            # If version ends with 'i', also download and extract interpreter
                            if self.needs_interpreter:
                                if self.download_interpreter(progress_dialog):
                                    if self.extract_interpreter(progress_dialog):
                                        wx.CallAfter(self.update_complete, progress_dialog, True)
                                    else:
                                        wx.CallAfter(self.update_complete, progress_dialog, False)
                                else:
                                    wx.CallAfter(self.update_complete, progress_dialog, False)
                            else:
                                wx.CallAfter(self.update_complete, progress_dialog, True)
                        else:
                            wx.CallAfter(self.update_complete, progress_dialog, False)
                    else:
                        wx.CallAfter(self.update_complete, progress_dialog, False)
                except Exception as e:
                    print(f"Update thread error: {e}")
                    wx.CallAfter(self.update_complete, progress_dialog, False)

            # Start update in separate thread
            thread = threading.Thread(target=update_thread, daemon=True)
            thread.start()

            return True

        except Exception as e:
            print(f"Error starting update: {e}")
            return False
    
    def update_complete(self, progress_dialog, success):
        """Handle update completion."""
        progress_dialog.Destroy()
        
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
            
            # Close application to allow restart
            if self.parent:
                self.parent.Close(True)
            else:
                sys.exit(0)
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
        """Main method to check for updates and show dialog if available."""
        has_update, current_version, new_version = self.check_for_updates()
        
        if has_update:
            changes = self.get_changes()
            
            if self.show_update_dialog(current_version, new_version, changes):
                return self.perform_update()
        
        return False


def check_for_updates_on_startup(parent=None):
    """Function to be called on application startup."""
    updater = Updater(parent)
    return updater.check_and_update()


if __name__ == "__main__":
    # Test the updater
    app = wx.App()
    
    updater = Updater()
    updater.check_and_update()
    
    app.MainLoop()