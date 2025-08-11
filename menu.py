# Filename: menu.py
import wx
import zipfile
import shutil
import os
import subprocess
from threading import Thread
from wx import ProgressDialog
from settingsgui import SettingsFrame
import traceback
from translation import set_language
from settings import get_setting

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

# Import the Component Manager GUI
try:
    from componentmanagergui import ComponentManagerDialog
    print("INFO: componentmanagergui.py imported successfully.")
except ImportError:
    ComponentManagerDialog = None
    print("ERROR: Failed to import componentmanagergui.py. Make sure the file exists and is in the correct path.")


class MenuBar(wx.MenuBar):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.component_manager = getattr(parent, 'component_manager', None)

        program_menu = wx.Menu()
        install_data_item = program_menu.Append(wx.ID_ANY, _("Install data package..."))
        component_manager_item = program_menu.Append(wx.ID_ANY, _("Component Manager..."))
        settings_item = program_menu.Append(wx.ID_ANY, _("Program settings"))
        minimize_item = program_menu.Append(wx.ID_ANY, _("Minimize"))
        exit_item = program_menu.Append(wx.ID_EXIT, _("Exit"))

        self.Bind(wx.EVT_MENU, self.on_install_data_package, install_data_item)
        self.Bind(wx.EVT_MENU, self.on_open_component_manager, component_manager_item)
        self.Bind(wx.EVT_MENU, self.on_open_settings, settings_item)
        self.Bind(wx.EVT_MENU, self.on_minimize, minimize_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)

        self.Append(program_menu, _("Program"))

        # Add components menu
        if self.component_manager:
            component_menu = wx.Menu()
            menu_functions = self.component_manager.get_component_menu_functions()
            for name, func in menu_functions.items():
                menu_item = component_menu.Append(wx.ID_ANY, name)
                self.Bind(wx.EVT_MENU, func, menu_item)
            
            if component_menu.GetMenuItemCount() > 0:
                self.Append(component_menu, _("Components"))


    def on_install_data_package(self, event):
        with wx.FileDialog(self.parent, _("Select data package"), wildcard=_("Data packages (*.zip;*.7z;*.tcepackage)|*.zip;*.7z;*.tcepackage"), style=wx.FD_OPEN) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
            file_path = dlg.GetPath()

            self.progress = ProgressDialog(_("Package installation"), _("Preparing for installation..."), maximum=100, parent=self.parent, style=wx.PD_AUTO_HIDE | wx.PD_APP_MODAL)

            Thread(target=self.extract_package, args=(file_path, self.progress), daemon=True).start()

    def on_open_component_manager(self, event):
        if ComponentManagerDialog and self.component_manager:
            manager_dialog = ComponentManagerDialog(self.parent, title=_("Component Manager"), component_manager=self.component_manager)
            manager_dialog.ShowModal()
            manager_dialog.Destroy()
        elif not ComponentManagerDialog:
             wx.MessageBox(_("Cannot load Component Manager (componentmanagergui.py not found)"), _("Error"), wx.OK | wx.ICON_ERROR)
        elif not self.component_manager:
             wx.MessageBox(_("Component Manager has not been initialized."), _("Error"), wx.OK | wx.ICON_ERROR)


    def update_progress_dialog(self, value, new_message=None):
        if hasattr(self, 'progress') and self.progress and self.progress.IsShown():
            if new_message:
                self.progress.Update(value, new_message)
            else:
                self.progress.Update(value)

    def destroy_progress_dialog(self):
        if hasattr(self, 'progress') and self.progress:
            self.progress.Destroy()
            self.progress = None

    def show_message_box(self, message, caption, style):
        wx.MessageBox(message, caption, style)


    def extract_package(self, file_path, progress):
        dest_dir = os.getcwd()
        result = None

        try:
            if file_path.endswith(".zip"):
                wx.CallAfter(self.update_progress_dialog, 0, _("Unpacking ZIP package..."))
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    total_files = len(zip_ref.namelist())
                    wx.CallAfter(progress.SetRange, total_files)
                    for i, file in enumerate(zip_ref.namelist(), 1):
                        zip_ref.extract(file, dest_dir)
                        wx.CallAfter(self.update_progress_dialog, i)

            elif file_path.endswith(".7z"):
                sevenzip_executable = os.path.join("data", "bin", "7z")
                if not os.path.exists(sevenzip_executable) and not (os.path.exists(sevenzip_executable + '.exe') and os.name == 'nt'):
                     wx.CallAfter(self.show_message_box, _("Error: 7z executable not found. Make sure it is in the 'data/bin/' directory."), _("Executable file error"), wx.OK | wx.ICON_ERROR)
                     return
                if os.name == 'nt' and not os.path.exists(sevenzip_executable) and os.path.exists(sevenzip_executable + '.exe'):
                    sevenzip_executable += '.exe'

                command = [sevenzip_executable, 'x', file_path, f'-o{dest_dir}', '-aoa']

                wx.CallAfter(self.update_progress_dialog, 0, _("Unpacking 7z package..."))
                wx.CallAfter(progress.SetRange, 100)
                wx.CallAfter(self.update_progress_dialog, 10, _("Starting 7z process..."))

                result = subprocess.run(command, capture_output=True, text=True, check=False)

                if result.returncode != 0:
                    error_message = f"7z extraction failed with error code {result.returncode}.\nStderr: {result.stderr}\nStdout: {result.stdout}"
                    wx.CallAfter(self.show_message_box, _("Error during package installation:\n{}").format(error_message), _("Error"), wx.OK | wx.ICON_ERROR)
                    return

                wx.CallAfter(self.update_progress_dialog, 100, _("Finished unpacking 7z."))


            elif file_path.endswith(".tcepackage"):
                wx.CallAfter(self.update_progress_dialog, 0, _("Unpacking .tcepackage package..."))
                wx.CallAfter(progress.SetRange, 100)
                wx.CallAfter(self.update_progress_dialog, 10, _("Unpacking archive..."))
                shutil.unpack_archive(file_path, dest_dir)
                wx.CallAfter(self.update_progress_dialog, 100, _("Finished unpacking .tcepackage."))


        except Exception as e:
            error_details = traceback.format_exc()
            wx.CallAfter(self.show_message_box, _("Error during package installation: {}\n\nDetails:\n{}").format(str(e), error_details), _("Error"), wx.OK | wx.ICON_ERROR)
        finally:
            if 'progress' in locals() and progress:
                 wx.CallAfter(self.destroy_progress_dialog)


        if 'e' not in locals() and not (file_path.endswith(".7z") and result and result.returncode != 0):
             wx.CallAfter(self.show_message_box, _("Data package has been installed!"), _("Success"), wx.OK | wx.ICON_INFORMATION)


    def on_open_settings(self, event):
        settings_frame = SettingsFrame(None, title=_("Settings"))
        settings_frame.Show()

    def on_minimize(self, event):
        self.parent.minimize_to_tray()

    def on_exit(self, event):
        self.parent.Close()
