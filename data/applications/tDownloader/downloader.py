import wx
import os
import platform
import configparser
import base64
import pygame
import threading
import requests
import subprocess
import sys
from datetime import datetime
from wx.lib.newevent import NewCommandEvent
import shutil
from translation import _

# Inicjalizacja Pygame do efektów dźwiękowych
pygame.mixer.init()

# TCE Speech: use Titan TTS engine (stereo speech) when available
try:
    from src.titan_core.tce_speech import speak as _tce_speak
except ImportError:
    _tce_speak = None

# Definicja efektów dźwiękowych
START_SOUND = "sfx/start.ogg"
END_SOUND = "sfx/downloadend.ogg"
ERROR_SOUND = "sfx/error.ogg"

def play_sound(sound_file):
    sound = pygame.mixer.Sound(sound_file)
    sound.play()

if _tce_speak is not None:
    def speak_message(message):
        """Announce a message via Titan TTS engine."""
        _tce_speak(message)
else:
    # Standalone fallback (outside Titan environment)
    try:
        import accessible_output3.outputs.auto as _ao3
        _ao3_speaker = _ao3.Auto()
    except Exception:
        _ao3_speaker = None

    def speak_message(message):
        """Announce a message via accessible_output3 with cross-platform fallback."""
        if _ao3_speaker:
            try:
                _ao3_speaker.speak(message, interrupt=True)
                return
            except Exception:
                pass
        try:
            _sys = platform.system()
            if _sys == 'Windows':
                import win32com.client
                win32com.client.Dispatch("SAPI.SpVoice").Speak(message)
            elif _sys == 'Darwin':
                subprocess.Popen(['say', message])
            else:
                subprocess.Popen(['spd-say', message])
        except Exception:
            pass

def get_notifications_path():
    if platform.system() == 'Windows':
        return os.path.join(os.getenv('APPDATA'), 'titosoft', 'Titan', 'bg5notifications.tno')
    elif platform.system() == 'Linux':
        return os.path.expanduser('~/.config/titosoft/Titan/bg5notifications.tno')
    elif platform.system() == 'Darwin':  # macOS
        return os.path.expanduser('~/Library/Application Support/titosoft/Titan/bg5notifications.tno')
    else:
        raise NotImplementedError(_('Unsupported platform'))

NOTIFICATIONS_FILE_PATH = get_notifications_path()

def create_notifications_file():
    os.makedirs(os.path.dirname(NOTIFICATIONS_FILE_PATH), exist_ok=True)
    with open(NOTIFICATIONS_FILE_PATH, 'w', encoding='utf-8') as file:
        file.write('')

def add_notification(appname, content):
    date = datetime.now().strftime("%Y-%m-%d")
    time = datetime.now().strftime("%H:%M:%S")
    with open(NOTIFICATIONS_FILE_PATH, 'a', encoding='utf-8') as file:
        file.write('notification\n')
        file.write(f'date={date}\n')
        file.write(f'time={time}\n')
        file.write(f'appname={appname}\n')
        file.write(f'content={content}\n\n')

class TitanDownloadManager(wx.Frame):
    def __init__(self, *args, **kw):
        super(TitanDownloadManager, self).__init__(*args, **kw)
        
        self.config = configparser.ConfigParser()
        self.config.read(get_settings_path())

        # Upewnij się, że ustawienia są kompletne
        self.ensure_settings_integrity()

        self.downloads = self.load_downloads()
        self.download_method = self.load_download_method()
        self.download_directory = self.load_download_directory()

        self.progress_dialog = None

        self.InitUI()

    def ensure_settings_integrity(self):
        """Upewnia się, że plik ustawień posiada wszystkie wymagane sekcje i klucze."""
        changed = False
        if not self.config.has_section('Settings'):
            self.config.add_section('Settings')
            changed = True

        # Upewnij się, że jest klucz method
        if 'method' not in self.config['Settings']:
            self.config['Settings']['method'] = 'python'
            changed = True

        # Upewnij się, że jest klucz download_directory
        if 'download_directory' not in self.config['Settings']:
            self.config['Settings']['download_directory'] = os.getcwd()
            changed = True

        if changed:
            os.makedirs(os.path.dirname(get_settings_path()), exist_ok=True)
            with open(get_settings_path(), 'w') as configfile:
                self.config.write(configfile)

    def InitUI(self):
        panel = wx.Panel(self)

        vbox = wx.BoxSizer(wx.VERTICAL)
        hbox_top = wx.BoxSizer(wx.HORIZONTAL)
        
        open_folder_btn = wx.Button(panel, label=_("Otwórz folder pobrań"))
        open_folder_btn.Bind(wx.EVT_BUTTON, self.OnOpenDownloadFolder)
        hbox_top.Add(open_folder_btn, flag=wx.ALL, border=5)

        vbox.Add(hbox_top, flag=wx.ALIGN_LEFT)
        
        self.list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT)
        self.list_ctrl.InsertColumn(0, _('Nazwa Pliku'), width=140)
        self.list_ctrl.InsertColumn(1, _('Link do Pobrania'), width=300)
        self.list_ctrl.SetName(_('Download list'))
        open_folder_btn.SetName(_('Open downloads folder'))

        self.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.OnRightClick, self.list_ctrl)

        vbox.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 20)

        self.load_download_list()
        
        menubar = wx.MenuBar()
        
        fileMenu = wx.Menu()
        newDownload = fileMenu.Append(wx.ID_NEW, _('&Nowe Pobranie'))
        self.Bind(wx.EVT_MENU, self.OnNewDownload, newDownload)
        settings = fileMenu.Append(wx.ID_PREFERENCES, _('&Ustawienia'))
        self.Bind(wx.EVT_MENU, self.OnSettings, settings)
        
        menubar.Append(fileMenu, _('&Plik'))
        
        self.SetMenuBar(menubar)
        
        self.SetTitle(_('Titan Download Manager'))
        self.Centre()

    def OnOpenDownloadFolder(self, event):
        # Otwórz folder pobierania w eksploratorze
        if platform.system() == 'Windows':
            os.startfile(self.download_directory)
        elif platform.system() == 'Darwin':
            subprocess.Popen(["open", self.download_directory])
        else:
            subprocess.Popen(["xdg-open", self.download_directory])

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
        
        os.makedirs(os.path.dirname(get_downloads_path()), exist_ok=True)
        with open(get_downloads_path(), 'w') as configfile:
            config.write(configfile)

    def load_download_method(self):
        self.config.read(get_settings_path())
        return self.config['Settings'].get('method', 'python')

    def load_download_directory(self):
        self.config.read(get_settings_path())
        return self.config['Settings'].get('download_directory', os.getcwd())

    def save_download_method(self, method):
        self.config.read(get_settings_path())
        if not self.config.has_section('Settings'):
            self.config.add_section('Settings')
        self.config['Settings']['method'] = method
        os.makedirs(os.path.dirname(get_settings_path()), exist_ok=True)
        with open(get_settings_path(), 'w') as configfile:
            self.config.write(configfile)
        
        if platform.system() == 'Windows' and method == 'wget':
            self.download_wget_for_windows()

    def save_download_directory(self, directory):
        self.config.read(get_settings_path())
        if not self.config.has_section('Settings'):
            self.config.add_section('Settings')
        self.config['Settings']['download_directory'] = directory
        os.makedirs(os.path.dirname(get_settings_path()), exist_ok=True)
        with open(get_settings_path(), 'w') as configfile:
            self.config.write(configfile)
        self.download_directory = directory

    def download_wget_for_windows(self):
        wget_exe_path = os.path.join(os.getcwd(), 'wget.exe')
        if os.path.exists(wget_exe_path):
            return  # Nie pobieraj ponownie, jeśli wget już istnieje

        wget_url = "https://eternallybored.org/misc/wget/1.21.3/64/wget.exe"

        def download_wget():
            play_sound(START_SOUND)
            wx.CallAfter(self.show_progress_dialog, _("Pobieranie"), _("Pobieranie wget.exe"))
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
                                progress = int(downloaded_length / total_length * 100) if total_length > 0 else 0
                                wx.CallAfter(self.update_progress_dialog, progress)
                play_sound(END_SOUND)
                wx.CallAfter(self.notify_completion, "wget.exe")
            except Exception as e:
                wx.CallAfter(self.show_error_message, str(e))
                play_sound(ERROR_SOUND)
            finally:
                wx.CallAfter(self.destroy_progress_dialog)

        threading.Thread(target=download_wget, daemon=True).start()

    def notify_completion(self, file_name):
        message = _('Pobieranie {} zakończone').format(file_name)
        add_notification(_("Titan Download Manager"), message)
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
        speak_message(_('Błąd podczas pobierania: {}').format(message))

    def show_error_message_gui(self, message):
        wx.MessageBox(_('Błąd podczas pobierania: {}').format(message), _('Błąd'), wx.OK | wx.ICON_ERROR)

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
        
        pause_item = wx.MenuItem(self, wx.NewId(), _('Wstrzymaj'))
        self.Append(pause_item)
        self.Bind(wx.EVT_MENU, self.OnPause, pause_item)
        
        stop_item = wx.MenuItem(self, wx.NewId(), _('Zatrzymaj'))
        self.Append(stop_item)
        self.Bind(wx.EVT_MENU, self.OnStop, stop_item)

        delete_file_item = wx.MenuItem(self, wx.NewId(), _('Usuń Plik'))
        self.Append(delete_file_item)
        self.Bind(wx.EVT_MENU, self.OnDeleteFile, delete_file_item)

        delete_list_item = wx.MenuItem(self, wx.NewId(), _('Usuń z Listy'))
        self.Append(delete_list_item)
        self.Bind(wx.EVT_MENU, self.OnDeleteList, delete_list_item)
        
    def OnPause(self, event):
        wx.MessageBox(_('Wstrzymaj pobieranie dla {}').format(self.file_name))
    
    def OnStop(self, event):
        wx.MessageBox(_('Zatrzymaj pobieranie dla {}').format(self.file_name))
    
    def OnDeleteFile(self, event):
        file_path = os.path.join(self.parent.download_directory, self.file_name)
        if os.path.exists(file_path):
            os.remove(file_path)
            wx.MessageBox(_('Plik {} został usunięty').format(self.file_name))
        else:
            wx.MessageBox(_('Plik {} nie istnieje').format(self.file_name))

    def OnDeleteList(self, event):
        self.parent.remove_download_from_list(self.file_name)
        wx.MessageBox(_('Plik {} został usunięty z listy').format(self.file_name))

class NewDownloadDialog(wx.Dialog):
    def __init__(self, parent, url_preset=None):
        super(NewDownloadDialog, self).__init__(parent, title=_("Nowe Pobranie"), size=(400, 200))
        
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        self.url = wx.TextCtrl(panel)
        
        # Ustaw URL jeśli został podany w argumencie
        if url_preset:
            self.url.SetValue(url_preset)
        else:
            clipboard_text = wx.TextDataObject()
            if wx.TheClipboard.Open():
                if wx.TheClipboard.GetData(clipboard_text):
                    self.url.SetValue(clipboard_text.GetText())
                wx.TheClipboard.Close()
        
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        ok_button = wx.Button(panel, label=_('OK'))
        close_button = wx.Button(panel, label=_('Zamknij'))
        
        self.Bind(wx.EVT_BUTTON, self.OnOk, ok_button)
        self.Bind(wx.EVT_BUTTON, self.OnClose, close_button)
        
        vbox.Add(wx.StaticText(panel, label=_("Wprowadź lub wklej link do pliku, który chcesz pobrać:")), flag=wx.ALL, border=10)
        vbox.Add(self.url, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)
        
        hbox.Add(ok_button)
        hbox.Add(close_button, flag=wx.LEFT, border=5)
        
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
            add_notification(_("Titan Download Manager"), _("Rozpoczęto pobieranie wget: {}").format(file_name))
            wx.CallAfter(self.show_progress_dialog, _("Pobieranie"), _("Pobieranie {}").format(file_name))
            try:
                download_path = os.path.join(self.GetParent().download_directory, file_name)
                if platform.system() == 'Windows':
                    wget_exe = os.path.join(os.getcwd(), 'wget.exe')  
                    subprocess.call([wget_exe, url, "-O", download_path])
                else:
                    subprocess.call(["wget", url, "-O", download_path])
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
            add_notification(_("Titan Download Manager"), _("Rozpoczęto pobieranie pliku: {}").format(file_name))
            wx.CallAfter(self.show_progress_dialog, _("Pobieranie"), _("Pobieranie {}").format(file_name))
            try:
                download_path = os.path.join(self.GetParent().download_directory, file_name)
                with requests.get(url, stream=True) as r:
                    r.raise_for_status()
                    total_length = r.headers.get('content-length')
                    if total_length is None:
                        total_length = 0
                    else:
                        total_length = int(total_length)
                    downloaded_length = 0
                    os.makedirs(self.GetParent().download_directory, exist_ok=True)
                    with open(download_path, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded_length += len(chunk)
                                if total_length > 0:
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
        message = _('Pobieranie {} zakończone').format(file_name)
        add_notification(_("Titan Download Manager"), message)
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
        speak_message(_('Błąd podczas pobierania: {}').format(message))

    def show_error_message_gui(self, message):
        wx.MessageBox(_('Błąd podczas pobierania: {}').format(message), _('Błąd'), wx.OK | wx.ICON_ERROR)
    
    def OnClose(self, event):
        self.Close()

class SettingsDialog(wx.Dialog):
    def __init__(self, parent):
        super(SettingsDialog, self).__init__(parent, title=_("Ustawienia"), size=(400, 300))
        
        panel = wx.Panel(self)
        main_vbox = wx.BoxSizer(wx.VERTICAL)
        
        # Sekcja metody pobierania
        method_box = wx.StaticBox(panel, label=_("Metoda pobierania plików"))
        method_sizer = wx.StaticBoxSizer(method_box, wx.VERTICAL)

        self.method_choice = wx.Choice(panel, choices=["python", "wget"])
        self.method_choice.SetStringSelection(parent.download_method)
        
        method_label = wx.StaticText(panel, label=_("Wybierz metodę pobierania:"))
        method_sizer.Add(method_label, flag=wx.LEFT | wx.TOP, border=10)
        method_sizer.Add(self.method_choice, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)
        
        main_vbox.Add(method_sizer, flag=wx.EXPAND | wx.ALL, border=10)

        # Sekcja folderu pobrań
        folder_box = wx.StaticBox(panel, label=_("Folder pobranych plików"))
        folder_sizer = wx.StaticBoxSizer(folder_box, wx.VERTICAL)
        
        folder_label = wx.StaticText(panel, label=_("Wybierz folder, w którym zapisywane będą pobrane pliki:"))
        self.dir_picker = wx.DirPickerCtrl(panel, path=parent.download_directory, style=wx.DIRP_USE_TEXTCTRL)
        self.dir_picker.SetToolTip(_("Wskaż folder, w którym mają być zapisywane pobrane pliki"))

        folder_sizer.Add(folder_label, flag=wx.LEFT | wx.TOP, border=10)
        folder_sizer.Add(self.dir_picker, flag=wx.EXPAND | wx.ALL, border=10)
        
        main_vbox.Add(folder_sizer, flag=wx.EXPAND | wx.ALL, border=10)
        
        # Przyciski
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        save_button = wx.Button(panel, label=_('Zapisz'))
        close_button = wx.Button(panel, label=_('Zamknij'))
        
        self.Bind(wx.EVT_BUTTON, self.OnSave, save_button)
        self.Bind(wx.EVT_BUTTON, self.OnClose, close_button)
        
        hbox.Add(save_button)
        hbox.Add(close_button, flag=wx.LEFT, border=5)
        
        main_vbox.Add(hbox, flag=wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, border=10)
        
        panel.SetSizer(main_vbox)
        
    def OnSave(self, event):
        self.GetParent().download_method = self.method_choice.GetStringSelection()
        self.GetParent().save_download_method(self.method_choice.GetStringSelection())
        
        new_dir = self.dir_picker.GetPath()
        self.GetParent().save_download_directory(new_dir)
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

    # Obsługa argumentów wiersza poleceń - automatyczne pobieranie jeśli podano URL
    if len(sys.argv) > 1:
        url_arg = sys.argv[1]
        # Prosta walidacja URL
        if url_arg.startswith("http://") or url_arg.startswith("https://"):
            dlg = NewDownloadDialog(frame, url_preset=url_arg)
            dlg.OnOk(None)  # Automatyczne rozpoczęcie pobierania

    app.MainLoop()
