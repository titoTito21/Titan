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
# Import the Component Manager GUI
try:
    from componentmanagergui import ComponentManagerFrame
    print("INFO: componentmanagergui.py imported successfully.")
except ImportError:
    ComponentManagerFrame = None
    print("ERROR: Failed to import componentmanagergui.py. Make sure the file exists and is in the correct path.")


class MenuBar(wx.MenuBar):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent # This parent should ideally be your main application frame
        # Get component_manager from parent. Print its value for debugging.
        self.component_manager = getattr(parent, 'component_manager', None)
        print(f"INFO: Component manager instance in MenuBar: {self.component_manager}")

        program_menu = wx.Menu()

        install_data_item = program_menu.Append(wx.ID_ANY, "Zainstaluj pakiet danych...")

        # Check conditions for adding the Component Manager menu item
        should_add_component_manager_menu = ComponentManagerFrame is not None and self.component_manager is not None
        print(f"INFO: Should add Component Manager menu item? {should_add_component_manager_menu}")
        print(f"INFO: ComponentManagerFrame is not None: {ComponentManagerFrame is not None}")
        print(f"INFO: self.component_manager is not None: {self.component_manager is not None}")

        if should_add_component_manager_menu:
            component_manager_item = program_menu.Append(wx.ID_ANY, "Menedżer komponentów...")

        settings_item = program_menu.Append(wx.ID_ANY, "Ustawienia programu")
        exit_item = program_menu.Append(wx.ID_EXIT, "Wyjście")

        self.Bind(wx.EVT_MENU, self.on_install_data_package, install_data_item)

        if should_add_component_manager_menu:
            self.Bind(wx.EVT_MENU, self.on_open_component_manager, component_manager_item)

        self.Bind(wx.EVT_MENU, self.on_open_settings, settings_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)

        self.Append(program_menu, "Program")


    def on_install_data_package(self, event):
        with wx.FileDialog(self.parent, "Wybierz pakiet danych", wildcard="Pakiety danych (*.zip;*.7z;*.tcepackage)|*.zip;*.7z;*.tcepackage", style=wx.FD_OPEN) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
            file_path = dlg.GetPath()

            self.progress = ProgressDialog("Instalacja pakietu", "Trwa przygotowanie do instalacji...", maximum=100, parent=self.parent, style=wx.PD_AUTO_HIDE | wx.PD_APP_MODAL)

            Thread(target=self.extract_package, args=(file_path, self.progress), daemon=True).start()

    def on_open_component_manager(self, event):
        if ComponentManagerFrame and self.component_manager:
            manager_frame = ComponentManagerFrame(self.parent, title="Menedżer komponentów", component_manager=self.component_manager)
            manager_frame.Show()
        elif not ComponentManagerFrame:
             wx.MessageBox("Nie można załadować menedżera komponentów (componentmanagergui.py nie znaleziono)", "Błąd", wx.OK | wx.ICON_ERROR)
        elif not self.component_manager:
             wx.MessageBox("Menedżer komponentów nie został zainicjalizowany.", "Błąd", wx.OK | wx.ICON_ERROR)


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
                wx.CallAfter(self.update_progress_dialog, 0, "Rozpakowywanie pakietu ZIP...")
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    total_files = len(zip_ref.namelist())
                    wx.CallAfter(progress.SetRange, total_files)
                    for i, file in enumerate(zip_ref.namelist(), 1):
                        zip_ref.extract(file, dest_dir)
                        wx.CallAfter(self.update_progress_dialog, i)

            elif file_path.endswith(".7z"):
                sevenzip_executable = os.path.join("data", "bin", "7z")
                if not os.path.exists(sevenzip_executable) and not (os.path.exists(sevenzip_executable + '.exe') and os.name == 'nt'):
                     wx.CallAfter(self.show_message_box, f"Błąd: Nie znaleziono pliku wykonywalnego 7z. Upewnij się, że znajduje się w katalogu 'data/bin/'.", "Błąd pliku wykonywalnego", wx.OK | wx.ICON_ERROR)
                     return
                if os.name == 'nt' and not os.path.exists(sevenzip_executable) and os.path.exists(sevenzip_executable + '.exe'):
                    sevenzip_executable += '.exe'

                command = [sevenzip_executable, 'x', file_path, f'-o{dest_dir}', '-aoa']

                wx.CallAfter(self.update_progress_dialog, 0, "Rozpakowywanie pakietu 7z...")
                wx.CallAfter(progress.SetRange, 100)
                wx.CallAfter(self.update_progress_dialog, 10, "Uruchamianie procesu 7z...")

                result = subprocess.run(command, capture_output=True, text=True, check=False)

                if result.returncode != 0:
                    error_message = f"7z extraction failed with error code {result.returncode}.\nStderr: {result.stderr}\nStdout: {result.stdout}"
                    wx.CallAfter(self.show_message_box, f"Błąd podczas instalacji pakietu:\n{error_message}", "Błąd", wx.OK | wx.ICON_ERROR)
                    return

                wx.CallAfter(self.update_progress_dialog, 100, "Zakończono rozpakowywanie 7z.")


            elif file_path.endswith(".tcepackage"):
                wx.CallAfter(self.update_progress_dialog, 0, "Rozpakowywanie pakietu .tcepackage...")
                wx.CallAfter(progress.SetRange, 100)
                wx.CallAfter(self.update_progress_dialog, 10, "Rozpakowywanie archiwum...")
                shutil.unpack_archive(file_path, dest_dir)
                wx.CallAfter(self.update_progress_dialog, 100, "Zakończono rozpakowywanie .tcepackage.")


        except Exception as e:
            error_details = traceback.format_exc()
            wx.CallAfter(self.show_message_box, f"Błąd podczas instalacji pakietu: {str(e)}\n\nSzczegóły:\n{error_details}", "Błąd", wx.OK | wx.ICON_ERROR)
        finally:
            if 'progress' in locals() and progress:
                 wx.CallAfter(self.destroy_progress_dialog)


        if 'e' not in locals() and not (file_path.endswith(".7z") and result and result.returncode != 0):
             wx.CallAfter(self.show_message_box, "Pakiet danych został zainstalowany!", "Sukces", wx.OK | wx.ICON_INFORMATION)


    def on_open_settings(self, event):
        settings_frame = SettingsFrame(None, title="Ustawienia")
        settings_frame.Show()

    def on_exit(self, event):
        self.parent.Close()