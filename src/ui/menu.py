# Filename: menu.py
import wx
import zipfile
import shutil
import os
import subprocess
from threading import Thread
from wx import ProgressDialog
from src.ui.settingsgui import SettingsFrame
import traceback
from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.ui.help import show_help
from src.titan_core.skin_manager import get_current_skin

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

# Import the Component Manager GUI
try:
    from src.ui.componentmanagergui import ComponentManagerDialog
    print("INFO: componentmanagergui.py imported successfully.")
except ImportError:
    ComponentManagerDialog = None
    print("ERROR: Failed to import componentmanagergui.py. Make sure the file exists and is in the correct path.")

# AI system now runs via voice commands only - no menu needed


class MenuBar(wx.MenuBar):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.component_manager = getattr(parent, 'component_manager', None)
        self.skin = get_current_skin()

        program_menu = wx.Menu()

        # Install data package with icon
        install_data_item = program_menu.Append(wx.ID_ANY, _("Install data package..."))
        try:
            install_data_item.SetBitmap(self.skin.get_icon('folder_icon', (16, 16)))
        except:
            pass

        # Component Manager with icon
        component_manager_item = program_menu.Append(wx.ID_ANY, _("Component Manager..."))
        try:
            component_manager_item.SetBitmap(self.skin.get_icon('components_icon', (16, 16)))
        except:
            pass

        # Add Titan-Net login option with icon - DISABLED
        # titan_net_login_item = program_menu.Append(wx.ID_ANY, _("Log in to Titan-Network..."))
        # try:
        #     titan_net_login_item.SetBitmap(self.skin.get_icon('titannet_icon', (16, 16)))
        # except:
        #     pass

        # Settings with icon
        settings_item = program_menu.Append(wx.ID_ANY, _("Program settings"))
        try:
            settings_item.SetBitmap(self.skin.get_icon('settings_icon', (16, 16)))
        except:
            pass

        program_menu.AppendSeparator()

        # Help with icon
        help_item = program_menu.Append(wx.ID_ANY, _("Help") + "\tF1")
        try:
            help_item.SetBitmap(self.skin.get_icon('help_icon', (16, 16)))
        except:
            pass

        program_menu.AppendSeparator()

        # Minimize with icon
        minimize_item = program_menu.Append(wx.ID_ANY, _("Minimize"))
        try:
            minimize_item.SetBitmap(self.skin.get_icon('close_icon', (16, 16)))
        except:
            pass

        # Exit with icon
        exit_item = program_menu.Append(wx.ID_EXIT, _("Exit"))
        try:
            exit_item.SetBitmap(self.skin.get_icon('shutdown_icon', (16, 16)))
        except:
            pass

        self.Bind(wx.EVT_MENU, self.on_install_data_package, install_data_item)
        self.Bind(wx.EVT_MENU, self.on_open_component_manager, component_manager_item)
        # self.Bind(wx.EVT_MENU, self.on_titan_net_login, titan_net_login_item)  # DISABLED
        self.Bind(wx.EVT_MENU, self.on_open_settings, settings_item)
        self.Bind(wx.EVT_MENU, self.on_show_help, help_item)
        self.Bind(wx.EVT_MENU, self.on_minimize, minimize_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)

        self.Append(program_menu, _("Program"))

        # Add switch menu
        switch_menu = wx.Menu()

        # Applications with icon
        switch_apps_item = switch_menu.Append(wx.ID_ANY, _("Applications"))
        try:
            switch_apps_item.SetBitmap(self.skin.get_icon('app_list_icon', (16, 16)))
        except:
            pass

        # Games with icon
        switch_games_item = switch_menu.Append(wx.ID_ANY, _("Games"))
        try:
            switch_games_item.SetBitmap(self.skin.get_icon('game_list_icon', (16, 16)))
        except:
            pass

        # Titan IM with icon
        switch_titanim_item = switch_menu.Append(wx.ID_ANY, _("Titan IM"))
        try:
            switch_titanim_item.SetBitmap(self.skin.get_icon('network_icon', (16, 16)))
        except:
            pass

        self.Bind(wx.EVT_MENU, self.on_switch_to_apps, switch_apps_item)
        self.Bind(wx.EVT_MENU, self.on_switch_to_games, switch_games_item)
        self.Bind(wx.EVT_MENU, self.on_switch_to_titanim, switch_titanim_item)

        self.Append(switch_menu, _("Switch to"))

        # Add components menu - show only components with menu functions
        if self.component_manager:
            component_menu = wx.Menu()
            menu_functions = self.component_manager.get_component_menu_functions()

            # Add menu items for components that registered functions
            for name, func in menu_functions.items():
                menu_item = component_menu.Append(wx.ID_ANY, name)
                self.Bind(wx.EVT_MENU, func, menu_item)

            # Only show Components menu if there are items
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
            # Restore window from tray if it's hidden
            if not self.parent.IsShown():
                self.parent.restore_from_tray()

            manager_dialog = ComponentManagerDialog(self.parent, title=_("Component Manager"), component_manager=self.component_manager)
            manager_dialog.ShowModal()
            manager_dialog.Destroy()
        elif not ComponentManagerDialog:
             wx.MessageBox(_("Cannot load Component Manager (componentmanagergui.py not found)"), _("Error"), wx.OK | wx.ICON_ERROR)
        elif not self.component_manager:
             wx.MessageBox(_("Component Manager has not been initialized."), _("Error"), wx.OK | wx.ICON_ERROR)

    # DISABLED - Titan-Net login
    # def on_titan_net_login(self, event):
    #     """Handle Titan-Net login from menu"""
    #     # Restore window from tray if it's hidden
    #     if not self.parent.IsShown():
    #         self.parent.restore_from_tray()

    #     # Check if titan_client exists
    #     if not hasattr(self.parent, 'titan_client') or not self.parent.titan_client:
    #         wx.MessageBox(_("Titan-Net client not initialized"), _("Error"), wx.OK | wx.ICON_ERROR)
    #         return

    #     # Check if already logged in
    #     if hasattr(self.parent, 'active_services') and "titannet" in self.parent.active_services:
    #         wx.MessageBox(_("You are already logged in to Titan-Network"), _("Information"), wx.OK | wx.ICON_INFORMATION)
    #         return

    #     # Import show_login_dialog
    #     from titan_net_gui import show_login_dialog

    #     # Show login dialog
    #     logged_in, offline_mode = show_login_dialog(self.parent, self.parent.titan_client)

    #     if logged_in:
    #         # Store in active services
    #         if hasattr(self.parent, 'active_services'):
    #             self.parent.active_services["titannet"] = {
    #                 "client": self.parent.titan_client,
    #                 "type": "titannet",
    #                 "name": "Titan-Net",
    #                 "online_users": [],
    #                 "unread_messages": {},
    #                 "user_data": {
    #                     "username": self.parent.titan_client.username,
    #                     "titan_number": self.parent.titan_client.titan_number
    #                 }
    #             }

    #         # Update UI if methods exist
    #         if hasattr(self.parent, 'populate_network_list'):
    #             self.parent.populate_network_list()
    #     elif offline_mode:
    #         # User chose offline mode
    #         # Application continues without Titan-Net connection
    #         pass

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
        # Use the existing settings_frame from parent instead of creating a new one
        settings_frame = getattr(self.parent, 'settings_frame', None)
        if settings_frame is None:
            # Fallback: create new one if not available (shouldn't happen in normal flow)
            settings_frame = SettingsFrame(None, title=_("Settings"))
        settings_frame.Show()

    def on_show_help(self, event):
        show_help()

    def on_minimize(self, event):
        self.parent.minimize_to_tray()

    def on_exit(self, event):
        self.parent.Close()

    def on_switch_to_apps(self, event):
        """Switch to Applications list"""
        if hasattr(self.parent, 'show_app_list'):
            self.parent.show_app_list()

    def on_switch_to_games(self, event):
        """Switch to Games list"""
        if hasattr(self.parent, 'show_game_list'):
            self.parent.show_game_list()

    def on_switch_to_titanim(self, event):
        """Switch to Titan IM"""
        if hasattr(self.parent, 'show_network_list'):
            self.parent.show_network_list()
