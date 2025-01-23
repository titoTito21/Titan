import wx
import yt_dlp
import subprocess
import os
from player import Player  # Import wbudowanego odtwarzacza
from pygame import mixer

class YoutubeSearchApp(wx.Frame):
    def __init__(self, parent, *args, **kwargs):
        super(YoutubeSearchApp, self).__init__(parent, *args, **kwargs)

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

        self.query = None
        self.videos = []

        # Inicjalizacja miksera dźwięków
        mixer.init()

        # Pobranie konfiguracji z rodzica (główne ustawienia)
        self.config = self.GetParent().config

    def on_search(self, event):
        query = self.search_field.GetValue()
        if query:
            self.query = query
            self.videos = []
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
