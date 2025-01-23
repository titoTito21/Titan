import wx
import os
import subprocess
import configparser
import threading
import requests
import yt_dlp
import sqlite3
from pygame import mixer
from urllib.parse import unquote, urljoin
import hashlib
import hmac
import time

from Settings import SettingsWindow
from player import Player  # Import wbudowanego odtwarzacza

# Funkcja do generowania nagłówków dla Podcast Index API
def generate_podcast_index_headers():
    api_key = "YOUR_API_KEY"  # Wstaw swój klucz API
    api_secret = "YOUR_API_SECRET"  # Wstaw swój sekret API
    now = int(time.time())
    data4hash = api_key + str(now)
    sha1hash = hmac.new(api_secret.encode('utf-8'), data4hash.encode('utf-8'), hashlib.sha1).hexdigest()

    headers = {
        'User-Agent': 'TMedia/1.0',
        'X-Auth-Key': api_key,
        'X-Auth-Date': str(now),
        'Authorization': sha1hash
    }
    return headers

# Funkcja do pobierania polskich stacji radiowych
def get_polish_radio_stations():
    url = "https://nl1.api.radio-browser.info/json/stations/bycountry/poland"
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()  # Zwraca listę stacji radiowych
    return []

# Funkcja do pobierania polskich podcastów
def get_polish_podcasts():
    headers = generate_podcast_index_headers()
    url = "https://api.podcastindex.org/api/1.0/search/byterm?q=poland&pretty"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get('feeds', [])  # Zwraca listę podcastów
    return []

# Funkcja do tworzenia połączenia z bazą danych SQLite
def create_db_connection(db_path='data/db.tdb'):
    if not os.path.exists('data'):
        os.makedirs('data')
    conn = sqlite3.connect(db_path)
    return conn

# Funkcja do tworzenia tabeli w bazie danych SQLite
def create_db_tables(conn):
    with conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS media_files (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            url TEXT UNIQUE,
                            name TEXT,
                            last_modified TEXT
                        )''')

# Funkcja do pobierania danych z bazy SQLite
def fetch_files_from_db(conn, base_url):
    with conn:
        cursor = conn.execute("SELECT name, url FROM media_files WHERE url LIKE ?", (base_url + '%',))
        return cursor.fetchall()

# Funkcja do aktualizacji danych w bazie SQLite
def update_db(conn, url, name, last_modified):
    with conn:
        conn.execute("INSERT OR IGNORE INTO media_files (url, name, last_modified) VALUES (?, ?, ?)", 
                     (url, name, last_modified))
        conn.execute("UPDATE media_files SET name = ?, last_modified = ? WHERE url = ?",
                     (name, last_modified, url))

# Funkcja do pobierania plików MP3 z katalogów URL z obsługą podkatalogów, polskich znaków i buforowania w SQLite
def get_files_from_url(media_tree, parent_node, base_url, conn, tts_thread, play_sound):
    total_files = 0  # Liczba wszystkich plików
    processed_files = 0  # Liczba przetworzonych plików
    previous_percentage = 0  # Poprzedni procent postępu

    def list_files_recursive(current_url, parent_node):
        nonlocal total_files, processed_files, previous_percentage

        try:
            response = requests.head(current_url, allow_redirects=True)
            last_modified = response.headers.get('Last-Modified', '')

            # Sprawdzenie, czy URL jest już w bazie danych
            cached_files = fetch_files_from_db(conn, current_url)
            if cached_files and cached_files[0][1] == last_modified:
                for file_name, file_url in cached_files:
                    if file_url.endswith('/'):  # To jest katalog
                        folder_node = media_tree.AppendItem(parent_node, file_name)
                        list_files_recursive(file_url, folder_node)
                    else:  # To jest plik MP3
                        file_node = media_tree.AppendItem(parent_node, file_name)
                        media_tree.SetItemData(file_node, file_url)
                        processed_files += 1
                return  # Pliki są aktualne, pomijamy dalsze przetwarzanie

            response = requests.get(current_url)
            if response.status_code == 200:
                lines = response.text.splitlines()

                # Zliczanie wszystkich plików do przetworzenia
                total_files += sum(1 for line in lines if 'href="' in line)

                for line in lines:
                    if 'href="' in line:
                        start = line.find('href="') + len('href="')
                        end = line.find('"', start)
                        link = line[start:end]
                        full_url = urljoin(current_url, link)
                        display_name = unquote(link).replace('%20', ' ').strip('/')

                        # Aktualizacja bazy danych
                        update_db(conn, full_url, display_name, last_modified)

                        if link.endswith('/'):  # To jest katalog
                            folder_node = media_tree.AppendItem(parent_node, display_name)
                            list_files_recursive(full_url, folder_node)
                        elif link.endswith('.mp3'):  # To jest plik MP3
                            # Prawidłowe dekodowanie polskich znaków do wyświetlania
                            display_name = unquote(display_name)
                            file_node = media_tree.AppendItem(parent_node, display_name)
                            media_tree.SetItemData(file_node, full_url)
                            processed_files += 1

                            # Obliczanie postępu na podstawie całkowitej liczby plików
                            if total_files > 0:
                                progress_percentage = int((processed_files / total_files) * 100)

                                # Zaktualizuj postęp tylko, jeśli procent jest większy niż poprzedni
                                if progress_percentage > previous_percentage:
                                    previous_percentage = progress_percentage
                                    if tts_thread:
                                        tts_thread.set_message(f"{progress_percentage}%")
                                    if play_sound:
                                        play_sound('click')

        except requests.ConnectionError:
            print(f"Connection Error: Unable to reach {current_url}")
            pass  # Ignoruje, jeśli nie można się połączyć

    list_files_recursive(base_url, parent_node)

# Funkcja do wczytywania katalogów URL z pliku data/urls.tmedia
def load_url_catalogs(media_tree, parent_node, conn, tts_thread, play_sound):
    urls_file = 'data/urls.tmedia'
    if os.path.exists(urls_file):
        with open(urls_file, 'r', encoding='utf-8') as f:
            for line in f:
                if '=' in line:
                    name, url = line.strip().split('=', 1)
                    catalog_node = media_tree.AppendItem(parent_node, name)
                    get_files_from_url(media_tree, catalog_node, url, conn, tts_thread, play_sound)

class TTSThread(threading.Thread):
    def __init__(self):
        super().__init__()
        self.message = None
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            if self.message:
                self.speak(self.message)
                self.message = None

    def speak(self, message):
        if os.name == 'nt':  # Windows
            import win32com.client as wincl
            speaker = wincl.Dispatch("SAPI.SpVoice")
            speaker.Speak(message)
        elif 'darwin' in os.sys.platform:  # macOS
            subprocess.run(['say', message])
        elif os.name == 'posix':  # Linux
            subprocess.run(['espeak', message])

    def interrupt(self):
        self._stop_event.set()

    def set_message(self, message):
        self.message = message

class TMediaApp(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(TMediaApp, self).__init__(*args, **kwargs)

        self.SetTitle("TMedia")
        self.SetSize((600, 400))
        panel = wx.Panel(self)

        self.config = self.load_settings()

        self.init_sounds()
        self.tts_thread = TTSThread()
        self.tts_thread.start()

        menubar = wx.MenuBar()
        fileMenu = wx.Menu()
        settings_item = fileMenu.Append(wx.ID_ANY, 'Ustawienia...')
        menubar.Append(fileMenu, '&Aplikacja')
        self.SetMenuBar(menubar)
        
        self.Bind(wx.EVT_MENU, self.open_settings, settings_item)

        vbox = wx.BoxSizer(wx.VERTICAL)

        self.function_list = wx.ListBox(panel, choices=["Katalog Mediów", "Wyszukiwarka YouTube"])
        vbox.Add(self.function_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        self.function_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_function_select)
        self.function_list.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)

        panel.SetSizer(vbox)

    def load_settings(self):
        config = configparser.ConfigParser()
        config_path = self.get_config_path()
        if not os.path.exists(os.path.dirname(config_path)):
            os.makedirs(os.path.dirname(config_path))
        if os.path.exists(config_path):
            config.read(config_path)
        else:
            config['DEFAULT'] = {
                'sound_effects': 'True',
                'tts_enabled': 'False',
                'player': 'tplayer'
            }
            with open(config_path, 'w') as configfile:
                config.write(configfile)
        return config

    def get_config_path(self):
        if os.name == 'nt':  # Windows
            return os.path.join(os.getenv('APPDATA'), 'Titosoft', 'Titan', 'appsettings', 'media.ini')
        elif os.name == 'posix':  # Linux, macOS
            if 'darwin' in os.sys.platform:  # macOS
                return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'Titosoft', 'Titan', 'appsettings', 'media.ini')
            else:  # Linux
                return os.path.join(os.path.expanduser('~'), '.config', 'Titosoft', 'Titan', 'appsettings', 'media.ini')

    def init_sounds(self):
        mixer.init()
        self.sounds = {
            'ding': mixer.Sound('sfx/ding.ogg'),
            'done': mixer.Sound('sfx/done.ogg'),
            'enter': mixer.Sound('sfx/enter.ogg'),
            'enteringtplayer': mixer.Sound('sfx/enteringtplayer.ogg'),
            'sound_on': mixer.Sound('sfx/sound_on.ogg'),
            'loading': mixer.Sound('sfx/loading.ogg'),
            'click': mixer.Sound('sfx/click.ogg')
        }

    def play_sound(self, sound_name):
        if self.config.getboolean('DEFAULT', 'sound_effects', fallback=True):
            sound = self.sounds.get(sound_name)
            if sound:
                sound.play()

    def stop_sound(self, sound_name):
        if self.config.getboolean('DEFAULT', 'sound_effects', fallback=True):
            sound = self.sounds.get(sound_name)
            if sound:
                sound.stop()

    def speak_message(self, message):
        if self.config.getboolean('DEFAULT', 'tts_enabled', fallback=False):
            self.tts_thread.set_message(message)

    def on_function_select(self, event):
        selection = self.function_list.GetSelection()
        if selection != wx.NOT_FOUND:
            self.play_sound('enter')
            if selection == 0:
                self.speak_message("Ładowanie katalogu mediów")
                self.load_media_catalog()
            elif selection == 1:
                self.open_youtube_search()

    def on_key_down(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self.on_function_select(None)
        else:
            event.Skip()

    def load_media_catalog(self):
        print("Ładowanie katalogu mediów...")  # Debugging
        self.play_sound('loading')
        media_catalog = MediaCatalog(self)
        media_catalog.Show()
        print("MediaCatalog pokazany...")  # Debugging
        self.stop_sound('loading')
        self.play_sound('ding')

    def open_youtube_search(self):
        youtube_search = YoutubeSearchApp(self)
        youtube_search.Show()

    def open_settings(self, event):
        settings_window = SettingsWindow(self, self.config)
        settings_window.Show()

class MediaCatalog(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(MediaCatalog, self).__init__(*args, **kwargs)

        self.SetTitle("Katalog Mediów")
        self.SetSize((600, 400))
        panel = wx.Panel(self)

        vbox = wx.BoxSizer(wx.VERTICAL)

        self.media_tree = wx.TreeCtrl(panel)
        root = self.media_tree.AddRoot("Katalog Mediów")

        # Pobranie i dodanie stacji radiowych
        radio_node = self.media_tree.AppendItem(root, "Stacje Radiowe")
        stations = get_polish_radio_stations()
        for station in stations:
            station_item = self.media_tree.AppendItem(radio_node, station['name'])
            self.media_tree.SetItemData(station_item, station['url'])

        # Pobranie i dodanie podcastów
        podcast_node = self.media_tree.AppendItem(root, "Podcasty")
        podcasts = get_polish_podcasts()
        for podcast in podcasts:
            podcast_item = self.media_tree.AppendItem(podcast_node, podcast['title'])
            self.media_tree.SetItemData(podcast_item, podcast['url'])

        # Dodanie katalogu "Biblioteka Mediów"
        library_node = self.media_tree.AppendItem(root, "Biblioteka Mediów")
        conn = create_db_connection()
        create_db_tables(conn)
        load_url_catalogs(self.media_tree, library_node, conn, self.GetParent().tts_thread, self.GetParent().play_sound)

        vbox.Add(self.media_tree, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        panel.SetSizer(vbox)

        self.media_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.on_tree_item_activated)
        self.media_tree.Bind(wx.EVT_CHAR_HOOK, self.on_tree_key_down)

    def on_tree_item_activated(self, event):
        item = event.GetItem()
        if item:
            media_url = self.media_tree.GetItemData(item)
            if media_url:
                self.play_media(media_url)
                self.GetParent().play_sound('done')
                self.GetParent().speak_message("Strumień został załadowany")

    def on_tree_key_down(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            item = self.media_tree.GetSelection()
            if item:
                self.on_tree_item_activated(wx.TreeEvent(wx.wxEVT_TREE_ITEM_ACTIVATED, self.media_tree, item))
        else:
            event.Skip()

    def play_media(self, url):
        player = self.GetParent().config.get('DEFAULT', 'player', fallback='tplayer')

        # Dekodowanie URL dla VLC, aby uniknąć problemów z podwójnym kodowaniem
        url = unquote(url)

        if player == 'vlc':
            if os.name == 'nt':  # Windows
                vlc_path = "C:/Program Files/VideoLAN/VLC/vlc.exe"  # Upewnij się, że ścieżka do VLC jest poprawna
                subprocess.Popen([vlc_path, url])  # Popen pozwala uruchomić proces w tle
            elif os.name == 'posix':  # Linux, macOS
                subprocess.Popen(["vlc", url])  # Popen pozwala uruchomić proces w tle
        else:
            tplayer = Player(self)
            tplayer.play_file(url)
            tplayer.Show()
            self.GetParent().play_sound('enteringtplayer')
            self.GetParent().speak_message(f"Odtwarzacz: {unquote(url).split('/')[-1]}")

class YoutubeSearchApp(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(YoutubeSearchApp, self).__init__(*args, **kwargs)

        self.SetTitle("Wyszukiwarka YouTube")
        self.SetSize((600, 400))
        panel = wx.Panel(self)

        vbox = wx.BoxSizer(wx.VERTICAL)

        self.search_field = wx.TextCtrl(panel)
        vbox.Add(self.search_field, flag=wx.EXPAND | wx.ALL, border=10)

        self.search_button = wx.Button(panel, label="Szukaj")
        vbox.Add(self.search_button, flag=wx.ALL, border=10)
        self.search_button.Bind(wx.EVT_BUTTON, self.on_search)

        self.results_list = wx.ListBox(panel)
        vbox.Add(self.results_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)
        self.results_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_play_video)
        self.results_list.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)

        panel.SetSizer(vbox)

    def on_search(self, event):
        query = self.search_field.GetValue()
        if query:
            self.search_videos(query)

    def search_videos(self, query):
        self.results_list.Clear()
        ydl_opts = {'quiet': True}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(f"ytsearch10:{query}", download=False)
                self.videos = result['entries']
                for video in self.videos:
                    self.results_list.Append(video['title'])
            self.GetParent().play_sound('ding')
            self.GetParent().speak_message("Wyniki zostały załadowane")
        except Exception as e:
            self.GetParent().speak_message(f"Błąd podczas wyszukiwania: {str(e)}")

    def on_play_video(self, event):
        selection = self.results_list.GetSelection()
        if selection != wx.NOT_FOUND:
            video = self.videos[selection]
            self.stream_video(video)

    def on_key_down(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self.on_play_video(None)
        else:
            event.Skip()

    def stream_video(self, video):
        ydl_opts = {
            'format': 'best',
            'quiet': True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(video['webpage_url'], download=False)
                video_url = info_dict['url']

            player = self.GetParent().config.get('DEFAULT', 'player', fallback='tplayer')
            if player == 'vlc':
                if os.name == 'nt':  # Windows
                    vlc_path = "C:/Program Files/VideoLAN/VLC/vlc.exe"  # Upewnij się, że ścieżka do VLC jest poprawna
                    subprocess.Popen([vlc_path, video_url])  # Popen pozwala uruchomić proces w tle
                elif os.name == 'posix':  # Linux, macOS
                    subprocess.Popen(["vlc", video_url])  # Popen pozwala uruchomić proces w tle
            else:
                tplayer = Player(self)
                tplayer.play_file(video_url)
                tplayer.Show()
                self.GetParent().play_sound('enteringtplayer')
                self.GetParent().speak_message(f"Odtwarzacz: {video['title']}")
        except Exception as e:
            self.GetParent().speak_message(f"Błąd podczas odtwarzania: {str(e)}")

if __name__ == '__main__':
    app = wx.App()
    frame = TMediaApp(None)
    frame.Show()
    app.MainLoop()
