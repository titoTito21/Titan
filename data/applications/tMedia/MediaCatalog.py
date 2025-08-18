import wx
import requests
import os
import feedparser
import subprocess
from urllib.parse import unquote, quote, urljoin

from threading import Thread
from concurrent.futures import ThreadPoolExecutor
from player import Player  # Importowanie wbudowanego odtwarzacza



class MediaCatalog(wx.Frame):
    def __init__(self, parent, *args, **kwargs):
        super(MediaCatalog, self).__init__(parent, *args, **kwargs)
        self.SetTitle("Katalog Mediów")
        self.SetSize((600, 400))
        panel = wx.Panel(self)

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.media_tree = wx.TreeCtrl(panel)
        root = self.media_tree.AddRoot("Katalog Mediów")

        vbox.Add(self.media_tree, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        # Add progress bar
        self.progress_bar = wx.Gauge(panel, range=100, size=(-1, 20))
        vbox.Add(self.progress_bar, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)
        self.progress_bar.Hide() # Initially hidden

        panel.SetSizer(vbox)

        # Bindowanie zdarzeń
        self.media_tree.Bind(wx.EVT_TREE_ITEM_EXPANDING, self.on_item_expanding)
        self.media_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.on_tree_item_activated)
        self.media_tree.Bind(wx.EVT_CHAR_HOOK, self.on_tree_key_down)

        # Start initial data loading in a separate thread
        self.initial_load_thread = Thread(target=self._load_initial_data_threaded, args=(root,))
        self.initial_load_thread.daemon = True
        self.initial_load_thread.start()

        self.loading_sound_channel = None

    def _load_initial_data_threaded(self, root_node):
        wx.CallAfter(self.progress_bar.Show)
        self.loading_sound_channel = wx.CallAfter(self.GetParent().play_sound, 'loading', loop=True)

        with ThreadPoolExecutor(max_workers=3) as executor:
            future_stations = executor.submit(self._get_polish_radio_stations)
            future_podcasts = executor.submit(self._get_podcasts_data)
            future_urls = executor.submit(self._get_url_catalogs_data)

            stations = future_stations.result()
            podcasts_data = future_podcasts.result()
            url_catalogs_data = future_urls.result()

        # Now, update GUI on the main thread
        wx.CallAfter(self._populate_initial_tree, root_node, stations, podcasts_data, url_catalogs_data)

        wx.CallAfter(self.loading_complete_initial)
        wx.CallAfter(self.GetParent().stop_sound, 'loading')

    def _get_polish_radio_stations(self):
        """Pobiera listę polskich stacji radiowych z Radio-Browser API."""
        url = "https://de1.api.radio-browser.info/json/stations"
        try:
            response = requests.get(url, timeout=5) # Add timeout to prevent indefinite blocking
            if response.status_code == 200:
                all_stations = response.json()
                polish_stations = [
                    station for station in all_stations
                    if "countrycode" in station and station["countrycode"] == "PL"
                ]
                return polish_stations
        except requests.exceptions.RequestException as e:
            wx.CallAfter(self.show_error_message, f"Błąd podczas pobierania stacji radiowych: {e}")
        return []

    def _get_podcasts_data(self):
        """Pobiera dane podcastów z pliku podcastdb.tmedia."""
        podcast_file = 'data/podcastdb.tmedia'
        data = []
        if os.path.exists(podcast_file):
            try:
                with open(podcast_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if '=' in line:
                            name, rss_url = line.strip().split('=', 1)
                            data.append((name, rss_url))
            except Exception as e:
                wx.CallAfter(self.show_error_message, f"Błąd podczas ładowania podcastów z pliku {podcast_file}: {e}")
        else:
            wx.CallAfter(self.show_error_message, f"Plik podcastów nie znaleziony: {podcast_file}")
        return data

    def _get_url_catalogs_data(self):
        """Pobiera dane katalogów URL z pliku urls.tmedia."""
        urls_file = 'data/urls.tmedia'
        data = []
        if os.path.exists(urls_file):
            try:
                with open(urls_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if '=' in line:
                            name, url = line.strip().split('=', 1)
                            data.append((name, url))
            except Exception as e:
                wx.CallAfter(self.show_error_message, f"Błąd podczas ładowania katalogów URL z pliku {urls_file}: {e}")
        else:
            wx.CallAfter(self.show_error_message, f"Plik katalogów URL nie znaleziony: {urls_file}")
        return data

    def _populate_initial_tree(self, root_node, stations, podcasts_data, url_catalogs_data):
        # Dodanie sekcji dla stacji radiowych
        self.update_progress(10)
        radio_node = self.media_tree.AppendItem(root_node, "Stacje Radiowe")
        for i, station in enumerate(stations):
            item = self.media_tree.AppendItem(radio_node, station['name'])
            self.media_tree.SetItemData(item, station['url'])
            self.update_progress(10 + int((i / len(stations)) * 30))

        # Dodanie sekcji dla podcastów
        self.update_progress(40)
        podcast_node = self.media_tree.AppendItem(root_node, "Podcasty")
        for name, rss_url in podcasts_data:
            item = self.media_tree.AppendItem(podcast_node, name)
            self.media_tree.SetItemData(item, rss_url)
            self.media_tree.SetItemHasChildren(item, True)
        self.update_progress(70)

        # Dodanie katalogu "Biblioteka Mediów"
        self.update_progress(70) # Update progress for podcasts
        library_node = self.media_tree.AppendItem(root_node, "Biblioteka Mediów")
        for name, url in url_catalogs_data:
            item = self.media_tree.AppendItem(library_node, name)
            self.media_tree.SetItemData(item, url)
            self.media_tree.SetItemHasChildren(item, True)
        self.update_progress(100)
        self.media_tree.Expand(root_node) # Expand the root after initial load

    def _load_podcast_episodes(self, podcast_node, rss_url):
        """Ładuje wszystkie odcinki podcastu z kanału RSS po rozwinięciu."""
        def _load_and_populate():
            try:
                feed = feedparser.parse(rss_url)

                if feed.bozo:
                    wx.CallAfter(self.show_error_message, f"Błąd parsowania kanału RSS dla {rss_url}: {feed.bozo_exception}")
                    return

                for entry in feed.entries:
                    title = entry.title
                    if hasattr(entry, 'published'):
                        title += f" ({entry.published})"
                    episode_node = self.media_tree.AppendItem(podcast_node, title)

                    # Zapisz link do pliku audio w danych węzła
                    if entry.enclosures and len(entry.enclosures) > 0:
                        audio_url = entry.enclosures[0].href
                        self.media_tree.SetItemData(episode_node, (audio_url, title))
            except Exception as e:
                wx.CallAfter(self.show_error_message, f"Nieoczekiwany błąd podczas ładowania odcinków podcastu z {rss_url}: {e}")
        Thread(target=_load_and_populate).start()

    def on_item_expanding(self, event):
        """Ładuje zawartość katalogu lub odcinki podcastu, gdy użytkownik go rozwija."""
        item = event.GetItem()
        url = self.media_tree.GetItemData(item)
        if url and self.media_tree.GetChildrenCount(item) == 0:
            if 'http' in url:
                self.load_directory(item, url)
            else:  # Jeśli to jest podcast
                self._load_podcast_episodes(item, url)

    def load_directory(self, parent_node, base_url):
        """Funkcja do leniwego ładowania zawartości katalogu i podkatalogów."""

        def list_files_threaded():
            try:
                response = requests.get(base_url, timeout=10) # Dodano timeout
                if response.status_code == 200:
                    lines = response.text.splitlines()
                    total_lines = len(lines)
                    for i, line in enumerate(lines):
                        if 'href="' in line:
                            start = line.find('href="') + len('href="')
                            end = line.find('"', start)
                            link = line[start:end]
                            full_url = urljoin(base_url, link)
                            display_name = unquote(link).replace('%20', ' ').strip('/')

                            if link.endswith('/'):  # To jest katalog
                                folder_node = self.media_tree.AppendItem(parent_node, display_name)
                                self.media_tree.SetItemData(folder_node, full_url)
                                self.media_tree.SetItemHasChildren(folder_node, True)
                            elif link.endswith(('.mp3', '.wav', '.ogg', '.wma', '.flac', '.aac',
                                                '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv',
                                                '.webm', '.m4a')):  # To jest plik audio lub wideo
                                file_node = self.media_tree.AppendItem(parent_node, display_name)
                                self.media_tree.SetItemData(file_node, full_url)

            except requests.ConnectionError as e:
                wx.CallAfter(self.show_error_message, f"Błąd połączenia podczas ładowania katalogu {base_url}: {e}")
            except Exception as e:
                wx.CallAfter(self.show_error_message, f"Nieoczekiwany błąd podczas ładowania katalogu {base_url}: {e}")
            finally:
                wx.CallAfter(self.loading_complete, parent_node)

        thread = Thread(target=list_files_threaded)
        thread.daemon = True
        thread.start()

    def update_progress(self, value):
        self.progress_bar.SetValue(value)

    def loading_complete_initial(self):
        self.progress_bar.Hide()
        if self.loading_sound_channel:
            self.GetParent().stop_sound(channel=self.loading_sound_channel) # Stop loading sound
        self.GetParent().play_sound('ding') # Play ding sound

    def loading_complete(self, parent_node):
        self.progress_bar.Hide()
        if self.loading_sound_channel:
            self.GetParent().stop_sound(channel=self.loading_sound_channel) # Stop loading sound
        self.GetParent().play_sound('ding') # Play ding sound
        self.media_tree.Expand(parent_node)

    def on_tree_item_activated(self, event):
        """Obsługuje zdarzenie aktywacji elementu w drzewie (np. podwójne kliknięcie)."""
        item = event.GetItem()
        if item:
            media_url = self.media_tree.GetItemData(item)
            if media_url:
                if isinstance(media_url, tuple): # Sprawdź, czy to krotka (URL, tytuł)
                    url_to_play = media_url[0]
                    display_title = media_url[1]
                else:
                    url_to_play = media_url
                    display_title = unquote(url_to_play).split('/')[-1] # Domyślny tytuł z URL

                self.play_media(url_to_play)
                self.GetParent().play_sound('done')
                self.GetParent().speak_message(f"Odtwarzanie: {display_title}")

    def on_tree_key_down(self, event):
        """Obsługuje zdarzenia klawiszy w drzewie katalogów."""
        if event.GetKeyCode() == wx.WXK_RETURN:
            item = self.media_tree.GetSelection()
            if item:
                self.on_tree_item_activated(wx.TreeEvent(wx.wxEVT_TREE_ITEM_ACTIVATED, self.media_tree, item))
        else:
            event.Skip()

    def play_media(self, url):
        """Odtwarza wybrany strumień za pomocą VLC lub wbudowanego odtwarzacza."""
        player = self.GetParent().config.get('DEFAULT', 'player', fallback='tplayer')

        # URL powinien być już poprawnie zakodowany, więc przekazujemy go bezpośrednio
        # encoded_url = quote(url, safe="%/:=&?~#+!$,;'@()*[]") # Usunięto podwójne kodowanie
        encoded_url = url

        if player == 'vlc':
            if os.name == 'nt':
                vlc_path = "C:/Program Files/VideoLAN/VLC/vlc.exe"
                subprocess.Popen([vlc_path, encoded_url])
            elif os.name == 'posix':
                subprocess.Popen(["vlc", encoded_url])
        else:
            tplayer = Player(self)
            tplayer.play_file(encoded_url)
            tplayer.Show()
            self.GetParent().play_sound('enteringtplayer')
            self.GetParent().speak_message(f"Odtwarzacz: {unquote(url).split('/')[-1]}")

    def show_error_message(self, message):
        wx.MessageBox(message, "Błąd ładowania", wx.OK | wx.ICON_ERROR)
