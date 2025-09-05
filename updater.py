import wx
import threading
import requests
import os
import sys
import subprocess
import time
from sound import play_sound, play_focus_sound, play_select_sound
from translation import _

class UpdateDialog(wx.Dialog):
    def __init__(self, parent, current_version, new_version, changes):
        super().__init__(parent, title=_("Program Update Available"), 
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        
        self.current_version = current_version
        self.new_version = new_version
        self.changes = changes
        
        self.init_ui()
        self.bind_events()
        
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
        play_sound('newupdate.ogg')
        
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
        
        # Start playing installation sound in background
        play_sound('installingapps.ogg')
    
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
        self.version_url = "http://titosofttitan.com/titan/titanchk/version.ver"
        self.changes_url = "http://titosofttitan.com/titan/titanchk/changes.txt"
        self.download_url = "http://titosofttitan.com/titan/titan.main.7z"
        self.temp_file = "titan_update.7z"
        self.seven_zip_path = os.path.join("data", "bin", "7z.exe")
    
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
            remote_version = response.text.strip()
            
            # Compare versions (simple string comparison)
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
    
    def extract_update(self, progress_dialog):
        """Extract update using 7zip."""
        try:
            progress_dialog.update_progress(0, _("Extracting update..."))
            
            if not os.path.exists(self.seven_zip_path):
                print(f"7zip not found at {self.seven_zip_path}")
                return False
            
            # Extract to current directory
            cmd = [self.seven_zip_path, 'x', self.temp_file, '-y', '-o.']
            
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                                     stderr=subprocess.PIPE, text=True)
            
            # Monitor extraction progress (simplified)
            while process.poll() is None:
                progress_dialog.update_progress(50, _("Extracting update..."))
                time.sleep(0.5)
            
            returncode = process.wait()
            
            if returncode == 0:
                progress_dialog.update_progress(100, _("Update extracted successfully"))
                return True
            else:
                print(f"7zip extraction failed with code {returncode}")
                return False
                
        except Exception as e:
            print(f"Error extracting update: {e}")
            return False
        finally:
            # Clean up temp file
            try:
                if os.path.exists(self.temp_file):
                    os.remove(self.temp_file)
            except:
                pass
    
    def perform_update(self):
        """Perform the full update process."""
        try:
            # Show progress dialog
            progress_dialog = ProgressDialog(self.parent)
            progress_dialog.Show()
            
            def update_thread():
                try:
                    # Download update
                    if self.download_update(progress_dialog):
                        # Extract update
                        if self.extract_update(progress_dialog):
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
            # Show success message
            wx.MessageBox(_("Update completed successfully! Please restart the application."),
                         _("Update Complete"), wx.OK | wx.ICON_INFORMATION)
            
            # Close application to allow restart
            if self.parent:
                self.parent.Close(True)
            else:
                sys.exit(0)
        else:
            # Show error message
            wx.MessageBox(_("Update failed. Please try again later."),
                         _("Update Error"), wx.OK | wx.ICON_ERROR)
    
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