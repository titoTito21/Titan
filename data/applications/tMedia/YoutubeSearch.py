import wx
import yt_dlp
import subprocess
import os
import webbrowser
from player import Player  # Import wbudowanego odtwarzacza
from pygame import mixer
from translation import _

class YoutubeSearchApp(wx.Frame):
    def __init__(self, parent, *args, **kwargs):
        super(YoutubeSearchApp, self).__init__(parent, *args, **kwargs)

        self.SetTitle(_("Wyszukiwarka YouTube"))
        self.SetSize((600, 400))
        panel = wx.Panel(self)

        vbox = wx.BoxSizer(wx.VERTICAL)

        self.search_field = wx.TextCtrl(panel)
        vbox.Add(self.search_field, flag=wx.EXPAND | wx.ALL, border=10)

        self.search_button = wx.Button(panel, label=_("Szukaj"))
        vbox.Add(self.search_button, flag=wx.ALL, border=10)
        self.search_button.Bind(wx.EVT_BUTTON, self.on_search)

        self.results_list = wx.ListBox(panel)
        vbox.Add(self.results_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)
        self.results_list.Bind(wx.EVT_LISTBOX_DCLICK, self._show_selection_context_menu)
        self.results_list.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)
        self.results_list.Bind(wx.EVT_RIGHT_DOWN, self.on_right_click)

        panel.SetSizer(vbox)

        self.query = None
        self.videos = []

        # Inicjalizacja miksera dźwięków
        mixer.init()

        # Pobranie konfiguracji z rodzica (główne ustawienia)
        self.config = self.GetParent().config

    def on_search(self, event):
        self.GetParent().play_sound('enter')
        query = self.search_field.GetValue()
        if query:
            self.query = query
            self.videos = []
            self.search_videos(query)

    def search_videos(self, query):
        self.results_list.Clear()
        self.GetParent().play_sound('loading')

        ydl_opts = {'quiet': True}

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(f"ytsearch10:{query}", download=False)
                self.videos = result['entries']
                for video in self.videos:
                    self.results_list.Append(video['title'])
            self.GetParent().play_sound('ding')
            self.GetParent().speak_message(_("Wyniki zostały załadowane"))
        except Exception as e:
            self.GetParent().speak_message(_("Błąd podczas wyszukiwania: %s") % str(e))

    def _show_selection_context_menu(self, event=None):
        selection = self.results_list.GetSelection()
        if selection != wx.NOT_FOUND:
            self.results_list.SetSelection(selection) # Ensure the item is selected

            menu = wx.Menu()
            play_item = menu.Append(wx.ID_ANY, "Odtwórz")
            download_item = menu.Append(wx.ID_ANY, "Pobierz")
            open_browser_item = menu.Append(wx.ID_ANY, "Otwórz w przeglądarce")

            self.Bind(wx.EVT_MENU, self.on_play_video_context, play_item)
            self.Bind(wx.EVT_MENU, self.on_download_video, download_item)
            self.Bind(wx.EVT_MENU, self.on_open_in_browser, open_browser_item)

            # Determine position for the context menu
            if event and hasattr(event, 'GetPosition'): # Check if it's a mouse event
                pos = event.GetPosition()
            else: # For keyboard events (Enter)
                # For ListBox, we can't get item rect directly.
                # Instead, we'll show the menu at the current mouse position or a default position.
                # A simple approach is to show it at the center of the listbox or at the top-left.
                # For now, let's use the current mouse position if available, otherwise a default.
                pos = self.results_list.GetPosition()
                pos = self.results_list.ClientToScreen(pos)

            self.results_list.PopupMenu(menu, pos)
            menu.Destroy()

    def on_key_down(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self._show_selection_context_menu() # Call the new method
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

            player = self.config.get('DEFAULT', 'player', fallback='tplayer')
            if player == 'vlc':
                if os.name == 'nt':  # Windows
                    vlc_path = "C:/Program Files/VideoLAN/VLC/vlc.exe"
                    subprocess.Popen([vlc_path, video_url])
                elif os.name == 'posix':  # Linux, macOS
                    subprocess.Popen(["vlc", video_url])
            else:
                tplayer = Player(self)
                tplayer.play_file(video_url)
                tplayer.Show()
                self.GetParent().play_sound('enteringtplayer')
                self.GetParent().speak_message(f"Odtwarzacz: {video['title']}")
        except Exception as e:
            self.GetParent().speak_message(f"Błąd podczas odtwarzania: {str(e)}")

    def on_right_click(self, event):
        selection = self.results_list.GetSelection()
        if selection != wx.NOT_FOUND:
            self.results_list.SetSelection(selection) # Select the item that was right-clicked
            menu = wx.Menu()
            play_item = menu.Append(wx.ID_ANY, "Odtwórz")
            download_item = menu.Append(wx.ID_ANY, "Pobierz")
            open_browser_item = menu.Append(wx.ID_ANY, "Otwórz w przeglądarce")

            self.Bind(wx.EVT_MENU, self.on_play_video_context, play_item)
            self.Bind(wx.EVT_MENU, self.on_download_video, download_item)
            self.Bind(wx.EVT_MENU, self.on_open_in_browser, open_browser_item)

            self.PopupMenu(menu, event.GetPosition())
            menu.Destroy()

    def on_play_video_context(self, event):
        selection = self.results_list.GetSelection()
        if selection != wx.NOT_FOUND:
            video = self.videos[selection]
            self.stream_video(video)

    def on_download_video(self, event):
        selection = self.results_list.GetSelection()
        if selection != wx.NOT_FOUND:
            video = self.videos[selection]
            self.download_video(video)

    def on_open_in_browser(self, event):
        selection = self.results_list.GetSelection()
        if selection != wx.NOT_FOUND:
            video = self.videos[selection]
            webbrowser.open(video['webpage_url'])

    def download_video(self, video):
        with wx.FileDialog(self, "Zapisz plik", wildcard="Wszystkie pliki (*.*)|*.*",
                           style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return

            pathname = fileDialog.GetPath()
            ydl_opts = {
                'format': 'best',
                'outtmpl': pathname,
                'noplaylist': True,
                'progress_hooks': [self.download_progress_hook],
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([video['webpage_url']])
                self.GetParent().speak_message(f"Pobieranie zakończone: {video['title']}")
            except Exception as e:
                self.GetParent().speak_message(f"Błąd podczas pobierania: {str(e)}")

    def download_progress_hook(self, d):
        if d['status'] == 'finished':
            self.GetParent().speak_message("Pobieranie zakończone.")
        if d['status'] == 'downloading':
            p = d['_percent_str']
            self.GetParent().speak_message(f"Pobieranie: {p}")
