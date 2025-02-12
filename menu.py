import wx
import zipfile
import py7zr
import shutil
import os
from threading import Thread
from wx import ProgressDialog
from settingsgui import SettingsFrame

class MenuBar(wx.MenuBar):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        program_menu = wx.Menu()
        
        install_data_item = program_menu.Append(wx.ID_ANY, "Zainstaluj pakiet danych...")
        settings_item = program_menu.Append(wx.ID_ANY, "Ustawienia programu")
        exit_item = program_menu.Append(wx.ID_EXIT, "Wyjście")
        
        self.Bind(wx.EVT_MENU, self.on_install_data_package, install_data_item)
        self.Bind(wx.EVT_MENU, self.on_open_settings, settings_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        
        self.Append(program_menu, "Program")
    
    def on_install_data_package(self, event):
        with wx.FileDialog(self.parent, "Wybierz pakiet danych", wildcard="Pakiety danych (*.zip;*.7z;*.tcepackage)|*.zip;*.7z;*.tcepackage", style=wx.FD_OPEN) as dlg:
            if dlg.ShowModal() == wx.ID_CANCEL:
                return
            file_path = dlg.GetPath()
            Thread(target=self.extract_package, args=(file_path,), daemon=True).start()
    
    def extract_package(self, file_path):
        dest_dir = os.getcwd()
        progress = ProgressDialog("Instalacja pakietu", "Trwa instalowanie pakietu danych...", maximum=100, parent=self.parent, style=wx.PD_AUTO_HIDE | wx.PD_APP_MODAL)
        
        try:
            if file_path.endswith(".zip"):
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    total_files = len(zip_ref.namelist())
                    for i, file in enumerate(zip_ref.namelist(), 1):
                        zip_ref.extract(file, dest_dir)
                        progress.Update(int((i / total_files) * 100))
            elif file_path.endswith(".7z"):
                sevenzip_path = os.path.join("data", "bin", "7z")
                with py7zr.SevenZipFile(file_path, 'r') as archive:
                    files = archive.getnames()
                    total_files = len(files)
                    for i, file in enumerate(files, 1):
                        archive.extract(targets=[file], path=dest_dir)
                        progress.Update(int((i / total_files) * 100))
            elif file_path.endswith(".tcepackage"):
                shutil.unpack_archive(file_path, dest_dir)
        except Exception as e:
            wx.MessageBox(f"Błąd podczas instalacji pakietu: {str(e)}", "Błąd", wx.OK | wx.ICON_ERROR)
        finally:
            progress.Destroy()
        wx.MessageBox("Pakiet danych został zainstalowany!", "Sukces", wx.OK | wx.ICON_INFORMATION)
    
    def on_open_settings(self, event):
        settings_frame = SettingsFrame(None, title="Ustawienia")
        settings_frame.Show()
    
    def on_exit(self, event):
        self.parent.Close()
