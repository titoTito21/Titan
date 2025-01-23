import wx
import requests
import os
import feedparser
import subprocess
from urllib.parse import unquote, quote, urljoin
from pygame import mixer
from threading import Thread
from player import Player  # Importowanie wbudowanego odtwarzacza

# Funkcja do odtwarzania dźwięku ładowania
def play_loading_sound(play_sound):
    """Rozpoczyna odtwarzanie dźwięku ładowania w pętli."""
    mixer.init()
    loading_sound = mixer.Sound('sfx/loading.ogg')
    loading_sound.play(loops=-1)  # Odtwarza dźwięk w pętli

# Funkcja do zatrzymania dźwięku ładowania
def stop_loading_sound():
    """Zatrzymuje odtwarzanie dźwięku ładowania."""
    mixer.stop()

class MediaCatalog(wx.Frame):
    def __init__(self, parent, *args, **kwargs):
        super(MediaCatalog, self).__init__(parent, *args, **kwargs)
        self.SetTitle("Katalog Mediów")
        self.SetSize((600, 400))
        panel = wx.Panel(self)

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.media_tree = wx.TreeCtrl(panel)
        root = self.media_tree.AddRoot("Katalog Mediów")

        # Dodanie sekcji dla stacji radiowych
        radio_node = self.media_tree.AppendItem(root, "Stacje Radiowe")
        stations = self.get_polish_radio_stations()
        for station in stations:
            station_item = self.media_tree.AppendItem(radio_node, station['name'])
            self.media_tree.SetItemData(station_item, station['url'])

        # Dodanie sekcji dla podcastów
        podcast_node = self.media_tree.AppendItem(root, "Podcasty")
        self.load_podcasts(podcast_node)

        # Dodanie katalogu "Biblioteka Mediów"
        library_node = self.media_tree.AppendItem(root, "Biblioteka Mediów")
        self.load_url_catalogs(library_node)

        vbox.Add(self.media_tree, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)
        panel.SetSizer(vbox)

        # Bindowanie zdarzeń
        self.media_tree.Bind(wx.EVT_TREE_ITEM_EXPANDING, self.on_item_expanding)
        self.media_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.on_tree_item_activated)
        self.media_tree.Bind(wx.EVT_CHAR_HOOK, self.on_tree_key_down)

    def get_polish_radio_stations(self):
        """Pobiera listę polskich stacji radiowych."""
        url = "https://nl1.api.radio-browser.info/json/stations/bycountry/poland"
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()  # Zwraca listę stacji radiowych
        return []

    def load_podcasts(self, parent_node):
        """Ładuje listę podcastów z pliku podcastdb.tmedia."""
        podcast_file = 'data/podcastdb.tmedia'  # Plik z listą podcastów w katalogu "data"
        if os.path.exists(podcast_file):
            with open(podcast_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if '=' in line:
                        name, rss_url = line.strip().split('=', 1)
                        podcast_node = self.media_tree.AppendItem(parent_node, name)
                        self.media_tree.SetItemData(podcast_node, rss_url)
                        self.media_tree.SetItemHasChildren(podcast_node, True)  # Oznacz, że podcast ma odcinki

    def load_podcast_episodes(self, podcast_node, rss_url):
        """Ładuje wszystkie odcinki podcastu z kanału RSS po rozwinięciu."""
        feed = feedparser.parse(rss_url)

        for entry in feed.entries:
            title = entry.title
            if hasattr(entry, 'published'):
                title += f" ({entry.published})"
            episode_node = self.media_tree.AppendItem(podcast_node, title)

            # Zapisz link do pliku audio w danych węzła
            if entry.enclosures and len(entry.enclosures) > 0:
                audio_url = entry.enclosures[0].href
                self.media_tree.SetItemData(episode_node, audio_url)

    def load_url_catalogs(self, parent_node):
        """Ładuje listę katalogów z pliku urls.tmedia."""
        urls_file = 'data/urls.tmedia'
        if os.path.exists(urls_file):
            with open(urls_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if '=' in line:
                        name, url = line.strip().split('=', 1)
                        catalog_node = self.media_tree.AppendItem(parent_node, name)
                        self.media_tree.SetItemData(catalog_node, url)
                        self.media_tree.SetItemHasChildren(catalog_node, True)  # Ustawia, że węzeł ma dzieci

    def on_item_expanding(self, event):
        """Ładuje zawartość katalogu lub odcinki podcastu, gdy użytkownik go rozwija."""
        item = event.GetItem()
        url = self.media_tree.GetItemData(item)
        if url and self.media_tree.GetChildrenCount(item) == 0:
            if 'http' in url:
                self.load_directory(item, url)
            else:  # Jeśli to jest podcast
                self.load_podcast_episodes(item, url)

    def load_directory(self, parent_node, base_url):
        """Funkcja do leniwego ładowania zawartości katalogu i podkatalogów."""
        def list_files(current_url, parent_node):
            try:
                response = requests.get(current_url)
                if response.status_code == 200:
                    lines = response.text.splitlines()
                    for line in lines:
                        if 'href="' in line:
                            start = line.find('href="') + len('href="')
                            end = line.find('"', start)
                            link = line[start:end]
                            full_url = urljoin(current_url, link)
                            display_name = unquote(link).replace('%20', ' ').strip('/')

                            if link.endswith('/'):  # To jest katalog
                                folder_node = self.media_tree.AppendItem(parent_node, display_name)
                                self.media_tree.SetItemData(folder_node, full_url)
                                self.media_tree.SetItemHasChildren(folder_node, True)
                            elif link.endswith(('.mp3', '.wav', '.ogg', '.wma', '.flac', '.aac', 
                    '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', 
                    '.webm', '.m4a')):  # To jest plik audio lub wideo
    # Kod obsługujący plik audio lub wideo

                                file_node = self.media_tree.AppendItem(parent_node, display_name)
                                self.media_tree.SetItemData(file_node, full_url)

            except requests.ConnectionError:
                print(f"Connection Error: Unable to reach {current_url}")
                pass

        play_loading_sound(self.GetParent().play_sound)
        list_files(base_url, parent_node)
        stop_loading_sound()
        self.media_tree.Expand(parent_node)

    def on_tree_item_activated(self, event):
        """Obsługuje zdarzenie aktywacji elementu w drzewie (np. podwójne kliknięcie)."""
        item = event.GetItem()
        if item:
            media_url = self.media_tree.GetItemData(item)
            if media_url:
                self.play_media(media_url)
                self.GetParent().play_sound('done')
                self.GetParent().speak_message("Strumień został załadowany")

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

        # Zakodowanie URL dla VLC i wbudowanego odtwarzacza
        encoded_url = quote(url, safe="%/:=&?~#+!$,;'@()*[]")

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
