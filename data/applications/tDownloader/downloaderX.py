import wx
import os
import platform
import configparser
import base64
import pygame
import threading
import requests
import subprocess
from datetime import datetime
import pyttsx3
from wx.lib.newevent import NewCommandEvent
import shutil

# Inicjalizacja Pygame do efektów dźwiękowych
pygame.mixer.init()

# Inicjalizacja pyttsx3 do komunikatów głosowych
engine = pyttsx3.init()

# Definicja efektów dźwiękowych
START_SOUND = "sfx/start.ogg"
END_SOUND = "sfx/downloadend.ogg"
ERROR_SOUND = "sfx/error.ogg"

def play_sound(sound_file):
    sound = pygame.mixer.Sound(sound_file)
    sound.play()

def speak_message(message):
    engine.say(message)
    engine.runAndWait()

# Funkcje powiadomień
def get_notifications_path():
    if platform.system() == 'Windows':
        return os.path.join(os.getenv('APPDATA'), 'titosoft', 'Titan', 'bg5notifications.tno')
    elif platform.system() == 'Linux':
        return os.path.expanduser('~/.config/titosoft/Titan/bg5notifications.tno')
    elif platform.system() == 'Darwin':  # macOS
        return os.path.expanduser('~/Library/Application Support/titosoft/Titan/bg5notifications.tno')
    else:
        raise NotImplementedError('Unsupported platform')

NOTIFICATIONS_FILE_PATH = get_notifications_path()

def create_notifications_file():
    os.makedirs(os.path.dirname(NOTIFICATIONS_FILE_PATH), exist_ok=True)
    with open(NOTIFICATIONS_FILE_PATH, 'w', encoding='utf-8') as file:
        file.write('')

def add_notification(appname, content):
    date = datetime.now().strftime("%Y-%m-%d")
    time = datetime.now().strftime("%H:%M:%S")
    with open(NOTIFICATIONS_FILE_PATH, 'a', encoding='utf-8') as file:
        file.write(f'notification\n')
        file.write(f'date={date}\n')
        file.write(f'time={time}\n')
        file.write(f'appname={appname}\n')
        file.write(f'content={content}\n\n')

class TitanDownloadManager(wx.Frame):
    def __init__(self, *args, **kw):
        super(TitanDownloadManager, self).__init__(*args, **kw)
        
        self.downloads = self.load_downloads()
        self.download_method = self.load_download_method()  # Domyślna metoda pobierania

        self.progress_dialog = None  # Przechowywanie referencji do paska postępu

        self.InitUI()

    def InitUI(self):
        panel = wx.Panel(self)

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT)
        self.list_ctrl.InsertColumn(0, 'Nazwa Pliku', width=140)
        self.list_ctrl.InsertColumn(1, 'Link do Pobrania', width=300)

        self.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.OnRightClick, self.list_ctrl)

        vbox.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 20)
        
        self.load_download_list()
        
        menubar = wx.MenuBar()
        
        fileMenu = wx.Menu()
        newDownload = fileMenu.Append(wx.ID_NEW, '&Nowe Pobranie')
        self.Bind(wx.EVT_MENU, self.OnNewDownload, newDownload)
        settings = fileMenu.Append(wx.ID_PREFERENCES, '&Ustawienia')
        self.Bind(wx.EVT_MENU, self.OnSettings, settings)
        
        menubar.Append(fileMenu, '&Plik')
        
        self.SetMenuBar(menubar)
        
        panel.SetSizer(vbox)
        
        self.SetTitle('Titan Download Manager')
        self.Centre()

    def load_downloads(self):
        config = configparser.ConfigParser()
        config.read(get_downloads_path())
        
        downloads = {}
        if config.has_section('Downloads'):
            for key in config['Downloads']:
                downloads[key] = decrypt(config['Downloads'][key])
        
        return downloads

    def save_downloads(self):
        config = configparser.ConfigParser()
        config['Downloads'] = {k: encrypt(v) for k, v in self.downloads.items()}
        
        with open(get_downloads_path(), 'w') as configfile:
            config.write(configfile)

    def load_download_method(self):
        config = configparser.ConfigParser()
        config.read(get_settings_path())
        if config.has_section('Settings') and 'method' in config['Settings']:
            return config['Settings']['method']
        return "python"

    def save_download_method(self, method):
        config = configparser.ConfigParser()
        config.read(get_settings_path())
        if not config.has_section('Settings'):
            config.add_section('Settings')
        config['Settings']['method'] = method
        with open(get_settings_path(), 'w') as configfile:
            config.write(configfile)
        
        if platform.system() == 'Windows' and method == 'wget':
            self.download_wget_for_windows()

    def download_wget_for_windows(self):
        wget_exe_path = os.path.join(os.getcwd(), 'wget.exe')
        if os.path.exists(wget_exe_path):
            return  # Nie pobieraj ponownie, jeśli wget już istnieje

        wget_url = "https://eternallybored.org/misc/wget/1.21.3/64/wget.exe"

        def download_wget():
            play_sound(START_SOUND)
            wx.CallAfter(self.show_progress_dialog, "Pobieranie", "Pobieranie wget.exe")
            try:
                with requests.get(wget_url, stream=True) as r:
                    r.raise_for_status()
                    total_length = r.headers.get('content-length')
                    if total_length is None:
                        total_length = 0
                    else:
                        total_length = int(total_length)
                    downloaded_length = 0
                    with open(wget_exe_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded_length += len(chunk)
                                progress = int(downloaded_length / total_length * 100)
                                wx.CallAfter(self.update_progress_dialog, progress)
                play_sound(END_SOUND)
                wx.CallAfter(self.notify_completion, "wget.exe")
            except Exception as e:
                wx.CallAfter(self.show_error_message, str(e))
                play_sound(ERROR_SOUND)
            finally:
                wx.CallAfter(self.destroy_progress_dialog)

        threading.Thread(target=download_wget).start()

    def notify_completion(self, file_name):
        message = f'Pobieranie {file_name} zakończone'
        add_notification("Titan Download Manager", message)
        speak_message(message)

    def show_progress_dialog(self, title, message):
        self.progress_dialog = wx.ProgressDialog(title, message, maximum=100, style=wx.PD_ELAPSED_TIME | wx.PD_REMAINING_TIME | wx.PD_AUTO_HIDE)
        self.progress_dialog.Show()

    def update_progress_dialog(self, progress):
        if self.progress_dialog:
            self.progress_dialog.Update(progress)

    def destroy_progress_dialog(self):
        if self.progress_dialog:
            self.progress_dialog.Destroy()
            self.progress_dialog = None

    def show_error_message(self, message):
        wx.CallAfter(self.show_error_message_gui, message)
        speak_message(f'Błąd podczas pobierania: {message}')

    def show_error_message_gui(self, message):
        wx.MessageBox(f'Błąd podczas pobierania: {message}', 'Błąd', wx.OK | wx.ICON_ERROR)

    def load_download_list(self):
        self.list_ctrl.DeleteAllItems()
        for file_name, url in self.downloads.items():
            index = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), file_name)
            self.list_ctrl.SetItem(index, 1, url)

    def remove_download_from_list(self, file_name):
        if file_name in self.downloads:
            del self.downloads[file_name]
            self.save_downloads()
            self.load_download_list()

    def OnRightClick(self, event):
        self.PopupMenu(RightClickMenu(self, self.list_ctrl.GetItemText(event.GetIndex())), event.GetPoint())

    def OnNewDownload(self, event):
        NewDownloadDialog(self).ShowModal()

    def OnSettings(self, event):
        SettingsDialog(self).ShowModal()

class RightClickMenu(wx.Menu):
    def __init__(self, parent, file_name):
        super(RightClickMenu, self).__init__()

        self.parent = parent
        self.file_name = file_name
        
        pause_item = wx.MenuItem(self, wx.NewId(), 'Wstrzymaj')
        self.Append(pause_item)
        self.Bind(wx.EVT_MENU, self.OnPause, pause_item)
        
        stop_item = wx.MenuItem(self, wx.NewId(), 'Zatrzymaj')
        self.Append(stop_item)
        self.Bind(wx.EVT_MENU, self.OnStop, stop_item)

        delete_file_item = wx.MenuItem(self, wx.NewId(), 'Usuń Plik')
        self.Append(delete_file_item)
        self.Bind(wx.EVT_MENU, self.OnDeleteFile, delete_file_item)

        delete_list_item = wx.MenuItem(self, wx.NewId(), 'Usuń z Listy')
        self.Append(delete_list_item)
        self.Bind(wx.EVT_MENU, self.OnDeleteList, delete_list_item)
        
    def OnPause(self, event):
        wx.MessageBox(f'Wstrzymaj pobieranie dla {self.file_name}')
    
    def OnStop(self, event):
        wx.MessageBox(f'Zatrzymaj pobieranie dla {self.file_name}')
    
    def OnDeleteFile(self, event):
        file_path = os.path.join(os.getcwd(), self.file_name)
        if os.path.exists(file_path):
            os.remove(file_path)
            wx.MessageBox(f'Plik {self.file_name} został usunięty')
        else:
            wx.MessageBox(f'Plik {self.file_name} nie istnieje')

    def OnDeleteList(self, event):
        self.parent.remove_download_from_list(self.file_name)
        wx.MessageBox(f'Plik {self.file_name} został usunięty z listy')

class NewDownloadDialog(wx.Dialog):
    def __init__(self, parent):
        super(NewDownloadDialog, self).__init__(parent, title="Nowe Pobranie", size=(400, 200))
        
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        self.url = wx.TextCtrl(panel)
        clipboard_text = wx.TextDataObject()
        if wx.TheClipboard.Open():
            if wx.TheClipboard.GetData(clipboard_text):
                self.url.SetValue(clipboard_text.GetText())
            wx.TheClipboard.Close()
        
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        ok_button = wx.Button(panel, label='OK')
        close_button = wx.Button(panel, label='Zamknij')
        
        self.Bind(wx.EVT_BUTTON, self.OnOk, ok_button)
        self.Bind(wx.EVT_BUTTON, self.OnClose, close_button)
        
        hbox.Add(ok_button)
        hbox.Add(close_button, flag=wx.LEFT, border=5)
        
        vbox.Add(self.url, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)
        vbox.Add(hbox, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=10)
        
        panel.SetSizer(vbox)
        
    def OnOk(self, event):
        url = self.url.GetValue()
        file_name = os.path.basename(url)
        self.GetParent().downloads[file_name] = url
        self.GetParent().save_downloads()
        self.GetParent().load_download_list()
        self.Close()

        if self.GetParent().download_method == "wget":
            self.start_wget_download(url, file_name)
        else:
            self.start_python_download(url, file_name)

    def start_wget_download(self, url, file_name):
        def download():
            play_sound(START_SOUND)
            add_notification("Titan Download Manager", f"Rozpoczęto pobieranie wget: {file_name}")
            wx.CallAfter(self.show_progress_dialog, "Pobieranie", f"Pobieranie {file_name}")
            try:
                if platform.system() == 'Windows':
                    wget_exe = os.path.join(os.getcwd(), 'wget.exe')  # Assuming wget.exe is in the same directory as this script
                    subprocess.call([wget_exe, url, "-O", file_name])
                else:
                    subprocess.call(["wget", url, "-O", file_name])
                play_sound(END_SOUND)
                wx.CallAfter(self.notify_completion, file_name)
            except Exception as e:
                wx.CallAfter(self.show_error_message, str(e))
                play_sound(ERROR_SOUND)
            finally:
                wx.CallAfter(self.destroy_progress_dialog)
        
        threading.Thread(target=download).start()

    def start_python_download(self, url, file_name):
        def download():
            play_sound(START_SOUND)
            add_notification("Titan Download Manager", f"Rozpoczęto pobieranie pliku: {file_name}")
            wx.CallAfter(self.show_progress_dialog, "Pobieranie", f"Pobieranie {file_name}")
            try:
                with requests.get(url, stream=True) as r:
                    r.raise_for_status()
                    total_length = r.headers.get('content-length')
                    if total_length is None:
                        total_length = 0
                    else:
                        total_length = int(total_length)
                    downloaded_length = 0
                    with open(file_name, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded_length += len(chunk)
                                progress = int(downloaded_length / total_length * 100)
                                wx.CallAfter(self.update_progress_dialog, progress)
                play_sound(END_SOUND)
                wx.CallAfter(self.notify_completion, file_name)
            except Exception as e:
                wx.CallAfter(self.show_error_message, str(e))
                play_sound(ERROR_SOUND)
            finally:
                wx.CallAfter(self.destroy_progress_dialog)

        threading.Thread(target=download).start()

    def notify_completion(self, file_name):
        message = f'Pobieranie {file_name} zakończone'
        add_notification("Titan Download Manager", message)
        speak_message(message)

    def show_progress_dialog(self, title, message):
        self.progress_dialog = wx.ProgressDialog(title, message, maximum=100, style=wx.PD_ELAPSED_TIME | wx.PD_REMAINING_TIME | wx.PD_AUTO_HIDE)
        self.progress_dialog.Show()

    def update_progress_dialog(self, progress):
        if self.progress_dialog:
            self.progress_dialog.Update(progress)

    def destroy_progress_dialog(self):
        if self.progress_dialog:
            self.progress_dialog.Destroy()
            self.progress_dialog = None

    def show_error_message(self, message):
        wx.CallAfter(self.show_error_message_gui, message)
        speak_message(f'Błąd podczas pobierania: {message}')

    def show_error_message_gui(self, message):
        wx.MessageBox(f'Błąd podczas pobierania: {message}', 'Błąd', wx.OK | wx.ICON_ERROR)
    
    def OnClose(self, event):
        self.Close()

class SettingsDialog(wx.Dialog):
    def __init__(self, parent):
        super(SettingsDialog, self).__init__(parent, title="Ustawienia", size=(300, 200))
        
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        self.method_choice = wx.Choice(panel, choices=["python", "wget"])
        self.method_choice.SetStringSelection(parent.download_method)
        
        vbox.Add(wx.StaticText(panel, label="Metoda pobierania plików:"), flag=wx.LEFT | wx.TOP, border=10)
        vbox.Add(self.method_choice, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)
        
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        save_button = wx.Button(panel, label='Zapisz')
        close_button = wx.Button(panel, label='Zamknij')
        
        self.Bind(wx.EVT_BUTTON, self.OnSave, save_button)
        self.Bind(wx.EVT_BUTTON, self.OnClose, close_button)
        
        hbox.Add(save_button)
        hbox.Add(close_button, flag=wx.LEFT, border=5)
        
        vbox.Add(hbox, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=10)
        
        panel.SetSizer(vbox)
        
    def OnSave(self, event):
        self.GetParent().download_method = self.method_choice.GetStringSelection()
        self.GetParent().save_download_method(self.method_choice.GetStringSelection())
        self.Close()
    
    def OnClose(self, event):
        self.Close()

def get_downloads_path():
    return os.path.join(os.getenv('APPDATA'), 'titosoft', 'titan', 'data', 'downloads.ini')

def get_settings_path():
    return os.path.join(os.getenv('APPDATA'), 'titosoft', 'titan', 'appsettings', 'tdm.ini')

def encrypt(data, key=b'secret'):
    return base64.b64encode(data.encode('utf-8')).decode('utf-8')

def decrypt(data, key=b'secret'):
    return base64.b64decode(data.encode('utf-8')).decode('utf-8')

if __name__ == '__main__':
    app = wx.App()
    create_notifications_file()
    frame = TitanDownloadManager(None)
    frame.Show()
    app.MainLoop()
