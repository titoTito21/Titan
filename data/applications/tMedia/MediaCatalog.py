import wx
import requests
import os
import html
import platform
import feedparser
import subprocess
from pathlib import Path
from urllib.parse import unquote, quote, urljoin, urlparse
from urllib.request import url2pathname

from threading import Thread
from concurrent.futures import ThreadPoolExecutor
from translation import _

import common

try:
    import win32api
except ImportError:
    win32api = None

MEDIA_FILE_EXTENSIONS = ('.mp3', '.wav', '.ogg', '.wma', '.flac', '.aac',
                          '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv',
                          '.webm', '.m4a')

GOOGLE_DRIVE_MARKER = 'googledrive://'


def _detect_google_drive_path():
    """Finds the drive letter Google Drive for Desktop is mounted on (Windows only)."""
    if platform.system() != 'Windows' or win32api is None:
        return None
    try:
        drives = win32api.GetLogicalDriveStrings().split('\x00')
    except Exception:
        return None
    for drive in drives:
        if not drive:
            continue
        try:
            volume_name = win32api.GetVolumeInformation(drive)[0]
        except Exception:
            continue
        if 'google drive' in volume_name.strip().lower():
            return drive
    return None


def _file_uri_to_path(uri):
    return url2pathname(urlparse(uri).path)


RADIO_BROWSER_COUNTRIES_URL = "https://de1.api.radio-browser.info/json/countries"
RADIO_BROWSER_STATIONS_URL = "https://de1.api.radio-browser.info/json/stations/bycountrycodeexact/"


class LanguagePickerDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Select Radio Language"), size=(450, 500))

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        self.status_label = wx.StaticText(panel, label=_("Loading available languages..."))
        vbox.Add(self.status_label, flag=wx.ALL, border=10)

        self.country_list = wx.ListBox(panel)
        vbox.Add(self.country_list, proportion=1, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=10)

        self.progress = wx.Gauge(panel, range=0, size=(-1, 15))
        vbox.Add(self.progress, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        btn_sizer = wx.StdDialogButtonSizer()
        self.ok_btn = wx.Button(panel, wx.ID_OK)
        self.ok_btn.Disable()
        btn_sizer.AddButton(self.ok_btn)
        self.cancel_btn = wx.Button(panel, wx.ID_CANCEL)
        btn_sizer.AddButton(self.cancel_btn)
        btn_sizer.Realize()
        vbox.Add(btn_sizer, flag=wx.ALL, border=10)

        panel.SetSizer(vbox)
        common.apply_skin(self)

        self.countries = []
        self.selected_country_code = None

        Thread(target=self._fetch_countries, daemon=True).start()

    def _fetch_countries(self):
        try:
            resp = requests.get(RADIO_BROWSER_COUNTRIES_URL, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                self.countries = [
                    c for c in data
                    if c.get("stationcount", 0) > 0
                ]
                self.countries.sort(key=lambda c: c.get("stationcount", 0), reverse=True)
                wx.CallAfter(self._populate_list)
            else:
                wx.CallAfter(self._show_error, _("Failed to load languages (HTTP %d)") % resp.status_code)
        except requests.RequestException as e:
            wx.CallAfter(self._show_error, _("Network error: %s") % str(e))

    def _populate_list(self):
        self.country_list.Clear()
        for c in self.countries:
            name = c.get("name", "?")
            count = c.get("stationcount", 0)
            self.country_list.Append(f"{name} ({count} {_('stations')})")
        self.status_label.SetLabel(_("Select a language and press OK"))
        self.ok_btn.Enable()
        self.progress.Pulse()

    def _show_error(self, msg):
        self.status_label.SetLabel(msg)
        self.progress.StopPulse()

    def get_selected_code(self):
        sel = self.country_list.GetSelection()
        if sel != wx.NOT_FOUND and sel < len(self.countries):
            return self.countries[sel].get("iso_3166_1")
        return None


class MediaCatalogPanel(wx.Panel):
    def __init__(self, parent, owner, *args, **kwargs):
        super(MediaCatalogPanel, self).__init__(parent, *args, **kwargs)
        self.owner = owner

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.media_tree = wx.TreeCtrl(self)
        root = self.media_tree.AddRoot(_("Media Catalog"))

        vbox.Add(self.media_tree, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        self.progress_bar = wx.Gauge(self, range=100, size=(-1, 20))
        vbox.Add(self.progress_bar, flag=wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)
        self.progress_bar.Hide()

        self.SetSizer(vbox)
        common.apply_skin(self)

        self.media_tree.Bind(wx.EVT_TREE_ITEM_EXPANDING, self.on_item_expanding)
        self.media_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.on_tree_item_activated)
        self.media_tree.Bind(wx.EVT_CHAR_HOOK, self.on_tree_key_down)

        self.loading_sound_channel = None
        self.root_node = root
        self._selected_country_code = None
        self.podcast_node = None

        wx.CallAfter(self._show_language_picker)

    def focus_default(self):
        self.media_tree.SetFocus()

    def _show_language_picker(self):
        dlg = LanguagePickerDialog(self)
        result = dlg.ShowModal()
        if result == wx.ID_OK:
            self._selected_country_code = dlg.get_selected_code()
        dlg.Destroy()

        if self._selected_country_code:
            self.initial_load_thread = Thread(
                target=self._load_initial_data_threaded,
                args=(self.root_node, self._selected_country_code),
                daemon=True,
            )
            self.initial_load_thread.start()
        else:
            self._load_without_radio()

    def _load_without_radio(self):
        self.progress_bar.Show()
        self.loading_sound_channel = common.play_sound('loading', loop=True)

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_podcasts = executor.submit(self._get_podcasts_data)
            future_urls = executor.submit(self._get_url_catalogs_data)
            podcasts_data = future_podcasts.result()
            url_catalogs_data = future_urls.result()

        wx.CallAfter(self._populate_tree_no_radio, self.root_node, podcasts_data, url_catalogs_data)
        wx.CallAfter(self.loading_complete_initial)
        wx.CallAfter(common.stop_sound, 'loading')

    def _load_initial_data_threaded(self, root_node, country_code):
        wx.CallAfter(self.progress_bar.Show)
        self.loading_sound_channel = wx.CallAfter(common.play_sound, 'loading', loop=True)

        with ThreadPoolExecutor(max_workers=3) as executor:
            future_stations = executor.submit(self._get_radio_stations, country_code)
            future_podcasts = executor.submit(self._get_podcasts_data)
            future_urls = executor.submit(self._get_url_catalogs_data)

            stations = future_stations.result()
            podcasts_data = future_podcasts.result()
            url_catalogs_data = future_urls.result()

        wx.CallAfter(self._populate_initial_tree, root_node, stations, podcasts_data, url_catalogs_data)
        wx.CallAfter(self.loading_complete_initial)
        wx.CallAfter(common.stop_sound, 'loading')

    def _get_radio_stations(self, country_code):
        try:
            response = requests.get(RADIO_BROWSER_STATIONS_URL + quote(country_code), timeout=15)
            if response.status_code == 200:
                return response.json()
        except requests.RequestException as e:
            wx.CallAfter(self.show_error_message, _("Error loading radio stations (%s): %s") % (country_code, e))
        return []

    def _get_podcasts_data(self):
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
                wx.CallAfter(self.show_error_message, _("Error loading podcasts from %s: %s") % (podcast_file, e))
        else:
            wx.CallAfter(self.show_error_message, _("Podcast file not found: %s") % podcast_file)
        return data

    def _get_url_catalogs_data(self):
        urls_file = 'data/urls.tmedia'
        data = []
        if os.path.exists(urls_file):
            try:
                with open(urls_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if '=' in line:
                            name, url = line.strip().split('=', 1)
                            if url.strip().lower() == GOOGLE_DRIVE_MARKER:
                                drive_path = _detect_google_drive_path()
                                if not drive_path:
                                    continue
                                url = Path(drive_path).as_uri()
                            data.append((name, url))
            except Exception as e:
                wx.CallAfter(self.show_error_message, _("Error loading URL catalogs from %s: %s") % (urls_file, e))
        else:
            wx.CallAfter(self.show_error_message, _("URL catalog file not found: %s") % urls_file)
        return data

    def _populate_initial_tree(self, root_node, stations, podcasts_data, url_catalogs_data):
        self.update_progress(5)
        radio_node = self.media_tree.AppendItem(root_node, _("Radio Stations"))

        for i, station in enumerate(stations):
            item = self.media_tree.AppendItem(radio_node, station['name'])
            self.media_tree.SetItemData(item, station['url'])
            self.update_progress(5 + int((i / max(len(stations), 1)) * 35))
        self.media_tree.SetItemHasChildren(radio_node, True)

        self.update_progress(40)
        podcast_node = self.media_tree.AppendItem(root_node, _("Podcasts"))
        self.podcast_node = podcast_node
        for name, rss_url in podcasts_data:
            item = self.media_tree.AppendItem(podcast_node, name)
            self.media_tree.SetItemData(item, rss_url)
            self.media_tree.SetItemHasChildren(item, True)
        self.update_progress(70)

        library_node = self.media_tree.AppendItem(root_node, _("Media Library"))
        for name, url in url_catalogs_data:
            item = self.media_tree.AppendItem(library_node, name)
            self.media_tree.SetItemData(item, url)
            self.media_tree.SetItemHasChildren(item, True)
        self.update_progress(100)
        self.media_tree.Expand(root_node)

    def _populate_tree_no_radio(self, root_node, podcasts_data, url_catalogs_data):
        self.update_progress(20)
        podcast_node = self.media_tree.AppendItem(root_node, _("Podcasts"))
        self.podcast_node = podcast_node
        for name, rss_url in podcasts_data:
            item = self.media_tree.AppendItem(podcast_node, name)
            self.media_tree.SetItemData(item, rss_url)
            self.media_tree.SetItemHasChildren(item, True)
        self.update_progress(60)

        library_node = self.media_tree.AppendItem(root_node, _("Media Library"))
        for name, url in url_catalogs_data:
            item = self.media_tree.AppendItem(library_node, name)
            self.media_tree.SetItemData(item, url)
            self.media_tree.SetItemHasChildren(item, True)
        self.update_progress(100)
        self.media_tree.Expand(root_node)

    def _load_podcast_episodes(self, podcast_node, rss_url):
        def _load_and_populate():
            try:
                feed = feedparser.parse(rss_url)
                if feed.bozo and not feed.entries:
                    wx.CallAfter(self.show_error_message, _("Error parsing RSS feed for %s: %s") % (rss_url, feed.bozo_exception))
                    return
                for entry in feed.entries:
                    title = entry.get('title', rss_url)
                    if entry.get('published'):
                        title += f" ({entry.published})"
                    episode_node = self.media_tree.AppendItem(podcast_node, title)
                    enclosures = entry.get('enclosures') or []
                    audio_url = enclosures[0].get('href') if enclosures else None
                    if audio_url:
                        self.media_tree.SetItemData(episode_node, (audio_url, title))
            except Exception as e:
                wx.CallAfter(self.show_error_message, _("Error loading podcast episodes from %s: %s") % (rss_url, e))
        Thread(target=_load_and_populate).start()

    def on_item_expanding(self, event):
        item = event.GetItem()
        url = self.media_tree.GetItemData(item)
        if url and self.media_tree.GetChildrenCount(item) == 0:
            if isinstance(url, str) and self.podcast_node is not None and self.media_tree.GetItemParent(item) == self.podcast_node:
                self._load_podcast_episodes(item, url)
            elif isinstance(url, str) and url.startswith('file://'):
                self.load_local_directory(item, url)
            elif isinstance(url, str) and 'http' in url:
                self.load_directory(item, url)

    def load_directory(self, parent_node, base_url):
        def list_files_threaded():
            try:
                response = requests.get(base_url, timeout=10)
                if response.status_code == 200:
                    lines = response.text.splitlines()
                    for line in lines:
                        if 'href="' in line:
                            start = line.find('href="') + len('href="')
                            end = line.find('"', start)
                            link = html.unescape(line[start:end])
                            full_url = urljoin(base_url, quote(link, safe='%/'))
                            display_name = unquote(link).replace('%20', ' ').strip('/')

                            if link.endswith('/'):
                                folder_node = self.media_tree.AppendItem(parent_node, display_name)
                                self.media_tree.SetItemData(folder_node, full_url)
                                self.media_tree.SetItemHasChildren(folder_node, True)
                            elif link.lower().endswith(MEDIA_FILE_EXTENSIONS):
                                file_node = self.media_tree.AppendItem(parent_node, display_name)
                                self.media_tree.SetItemData(file_node, full_url)
            except requests.ConnectionError as e:
                wx.CallAfter(self.show_error_message, _("Connection error loading catalog %s: %s") % (base_url, e))
            except Exception as e:
                wx.CallAfter(self.show_error_message, _("Error loading catalog %s: %s") % (base_url, e))
            finally:
                wx.CallAfter(self.loading_complete, parent_node)

        thread = Thread(target=list_files_threaded, daemon=True)
        thread.start()

    def load_local_directory(self, parent_node, base_url):
        def list_files_threaded():
            try:
                base_path = _file_uri_to_path(base_url)
                entries = sorted(os.scandir(base_path), key=lambda e: e.name.lower())
                for entry in entries:
                    if entry.is_dir():
                        full_url = Path(entry.path).as_uri()
                        folder_node = self.media_tree.AppendItem(parent_node, entry.name)
                        self.media_tree.SetItemData(folder_node, full_url)
                        self.media_tree.SetItemHasChildren(folder_node, True)
                    elif entry.name.lower().endswith(MEDIA_FILE_EXTENSIONS):
                        full_url = Path(entry.path).as_uri()
                        file_node = self.media_tree.AppendItem(parent_node, entry.name)
                        self.media_tree.SetItemData(file_node, full_url)
            except Exception as e:
                wx.CallAfter(self.show_error_message, _("Error loading catalog %s: %s") % (base_url, e))
            finally:
                wx.CallAfter(self.loading_complete, parent_node)

        thread = Thread(target=list_files_threaded, daemon=True)
        thread.start()

    def update_progress(self, value):
        self.progress_bar.SetValue(value)

    def loading_complete_initial(self):
        self.progress_bar.Hide()
        if self.loading_sound_channel:
            common.stop_sound(channel=self.loading_sound_channel)
        common.play_sound('ding')

    def loading_complete(self, parent_node):
        self.progress_bar.Hide()
        if self.loading_sound_channel:
            common.stop_sound(channel=self.loading_sound_channel)
        common.play_sound('ding')
        self.media_tree.Expand(parent_node)

    def on_tree_item_activated(self, event):
        item = event.GetItem()
        if item:
            media_url = self.media_tree.GetItemData(item)
            if media_url:
                if isinstance(media_url, tuple):
                    url_to_play = media_url[0]
                    display_title = media_url[1]
                else:
                    url_to_play = media_url
                    display_title = self.media_tree.GetItemText(item)

                self.play_media(url_to_play, display_title)
                common.play_sound('done')
                common.speak(_("Playing: %s") % display_title)

    def on_tree_key_down(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            item = self.media_tree.GetSelection()
            if item:
                self.on_tree_item_activated(wx.TreeEvent(wx.wxEVT_TREE_ITEM_ACTIVATED, self.media_tree, item))
        elif event.GetKeyCode() == wx.WXK_ESCAPE:
            self.owner.go_back()
        else:
            event.Skip()

    def play_media(self, url, title=None):
        player = common.config.get('DEFAULT', 'player', fallback='tplayer')

        if player == 'vlc':
            if os.name == 'nt':
                vlc_path = "C:/Program Files/VideoLAN/VLC/vlc.exe"
                subprocess.Popen([vlc_path, url])
            elif os.name == 'posix':
                subprocess.Popen(["vlc", url])
        else:
            display_title = title or unquote(url).split('/')[-1]
            common.play_sound('enteringtplayer')
            common.speak(_("Player: %s") % display_title)
            self.owner.play_media(url, title)

    def show_error_message(self, message):
        wx.MessageBox(message, _("Loading Error"), wx.OK | wx.ICON_ERROR)
