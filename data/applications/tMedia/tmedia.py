import wx
import os
import sys
from threading import Thread
from translation import _

import common
import playlist
from bookmarks_gui import BookmarksPanel
from MediaCatalog import MediaCatalogPanel
from Settings import SettingsWindow
from player import PlayerPanel
from YoutubeSearch import YoutubeSearchPanel


class FunctionListPanel(wx.Panel):
    """Root view: pick Media Catalog, YouTube Search or Bookmarks."""

    def __init__(self, parent, owner, *args, **kwargs):
        super(FunctionListPanel, self).__init__(parent, *args, **kwargs)
        self.owner = owner

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.function_list = wx.ListBox(self, choices=[_("Media Catalog"),
                                                       _("YouTube Search"),
                                                       _("Bookmarks")])
        self.function_list.SetName(_("TMedia functions"))
        vbox.Add(self.function_list, proportion=1, flag=wx.EXPAND | wx.ALL, border=10)

        self.function_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_function_select)
        self.function_list.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)

        self.SetSizer(vbox)
        common.apply_skin(self)

    def focus_default(self):
        self.function_list.SetFocus()

    def on_function_select(self, event):
        selection = self.function_list.GetSelection()
        if selection != wx.NOT_FOUND:
            common.play_sound('enter')
            if selection == 0:
                common.speak(_("Loading media catalog"))
                self.owner.show_view('media_catalog')
            elif selection == 1:
                self.owner.show_view('youtube_search')
            elif selection == 2:
                self.owner.show_view('bookmarks')

    def on_key_down(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self.on_function_select(None)
        else:
            event.Skip()


class TMediaApp(wx.Frame):
    """Single-window shell: a back button + one content area that swaps
    between the function list, the media catalog, YouTube search, and the
    player, instead of the old picker-window-plus-function-window pair."""

    def __init__(self, *args, initial_media=None, **kwargs):
        super(TMediaApp, self).__init__(*args, **kwargs)

        self.SetTitle("TMedia")
        self.SetSize((600, 400))

        self.views = {}
        self.view_stack = []
        self.current_view = None

        self.outer_panel = wx.Panel(self)
        outer_sizer = wx.BoxSizer(wx.VERTICAL)

        self.back_button = wx.Button(self.outer_panel, label=_("Back"))
        self.back_button.Bind(wx.EVT_BUTTON, lambda e: self.go_back())
        self.back_button.Hide()
        outer_sizer.Add(self.back_button, 0, wx.ALL, 5)

        self.view_container = wx.Panel(self.outer_panel)
        self.view_sizer = wx.BoxSizer(wx.VERTICAL)
        self.view_container.SetSizer(self.view_sizer)
        outer_sizer.Add(self.view_container, proportion=1, flag=wx.EXPAND)

        self.outer_panel.SetSizer(outer_sizer)

        menubar = wx.MenuBar()
        fileMenu = wx.Menu()
        bookmarks_item = fileMenu.Append(wx.ID_ANY, _('Bookmarks...'))
        settings_item = fileMenu.Append(wx.ID_ANY, _('Settings...'))
        menubar.Append(fileMenu, _('&Application'))
        self.SetMenuBar(menubar)

        self.Bind(wx.EVT_MENU, self.open_settings, settings_item)
        self.Bind(wx.EVT_MENU, self.open_bookmarks, bookmarks_item)

        self.show_view('function_list')

        if initial_media:
            self._start_initial_media(initial_media)

    def _start_initial_media(self, media):
        """Handle the startup argument. A normal file path or URL plays directly;
        a FOLDER (or an ``audiobook:<folder>`` argument) plays as an audiobook -
        the whole folder as one item, continuing from its saved position; a
        ``ytsearch:<query>`` argument (or a bare, non-file, non-URL string, e.g.
        one sent by the Titan assistant) triggers a YouTube search that
        auto-plays the first result; a ``radio:<country>:<query>`` argument opens
        the radio list for that country (skipping the country picker) and
        auto-plays the first station matching the query."""
        m = (media or '').strip()
        if not m:
            return
        audiobook_prefix = 'audiobook:'
        if m.lower().startswith(audiobook_prefix):
            target = m[len(audiobook_prefix):].strip()
            if target:
                self.play_folder(target)
            return
        if playlist.looks_like_folder(m):
            self.play_folder(m)
            return
        radio_prefix = 'radio:'
        if m.lower().startswith(radio_prefix):
            rest = m[len(radio_prefix):]
            parts = rest.split(':', 1)
            country = parts[0].strip() or None
            query = (parts[1].strip() if len(parts) > 1 else '') or None
            self._start_radio(country, query)
            return
        prefix = 'ytsearch:'
        if m.lower().startswith(prefix):
            query = m[len(prefix):].strip()
        elif ('://' in m) or os.path.exists(m):
            self.play_media(m)          # a real URL or local file
            return
        else:
            query = m                   # a bare search phrase
        if not query:
            return
        panel = self._get_or_create_view('youtube_search')
        self.show_view('youtube_search')
        search_and_play = getattr(panel, 'search_and_play_first', None)
        if callable(search_and_play):
            search_and_play(query)
        else:
            self.play_media(m)

    def _start_radio(self, country, query):
        """Open the media catalog straight into radio for ``country`` (skipping
        the interactive country picker) and let it auto-play a matching station.
        The panel is created with auto_start=False so it does not pop the picker;
        we then drive it with load_radio_direct."""
        panel = self.views.get('media_catalog')
        if panel is None:
            panel = MediaCatalogPanel(self.view_container, owner=self,
                                      auto_start=False)
            self.views['media_catalog'] = panel
            self.view_sizer.Add(panel, proportion=1, flag=wx.EXPAND)
            panel.Hide()
        self.show_view('media_catalog')
        panel.load_radio_direct(country, query)

    # ------------------------------------------------------------------ #
    # View stack
    # ------------------------------------------------------------------ #
    def _create_view(self, name):
        if name == 'function_list':
            return FunctionListPanel(self.view_container, owner=self)
        if name == 'media_catalog':
            return MediaCatalogPanel(self.view_container, owner=self)
        if name == 'youtube_search':
            return YoutubeSearchPanel(self.view_container, owner=self)
        if name == 'bookmarks':
            return BookmarksPanel(self.view_container, owner=self)
        raise ValueError(name)

    def _get_or_create_view(self, name):
        panel = self.views.get(name)
        if panel is None:
            panel = self._create_view(name)
            self.views[name] = panel
            self.view_sizer.Add(panel, proportion=1, flag=wx.EXPAND)
            panel.Hide()
        return panel

    def show_view(self, name, push=True):
        # The player view is destroyed and rebuilt for every new item, so
        # "already showing it" is only true while its panel still exists.
        if self.current_view == name and self.views.get(name) is not None:
            return
        if self.current_view == 'player' and name != 'player':
            self._destroy_player_view()

        panel = self._get_or_create_view(name)
        for key, existing in self.views.items():
            if existing is not panel:
                existing.Hide()
        panel.Show()

        if push and self.current_view is not None and self.current_view != name:
            self.view_stack.append(self.current_view)
        self.current_view = name

        self.back_button.Show(name != 'function_list')
        if name == 'function_list':
            self.SetTitle("TMedia")

        self.view_container.Layout()
        self.outer_panel.Layout()
        if hasattr(panel, 'focus_default'):
            panel.focus_default()
        else:
            panel.SetFocus()

    def go_back(self):
        if not self.view_stack:
            return
        previous = self.view_stack.pop()
        self.show_view(previous, push=False)

    def _destroy_player_view(self):
        panel = self.views.pop('player', None)
        if panel:
            panel.stop_and_cleanup()
            self.view_sizer.Detach(panel)
            panel.Destroy()

    def play_media(self, url, title=None, start_position=None):
        """Switch to the embedded player and start playback. This is what
        the media catalog / YouTube search views call instead of opening a
        second top-level Player window."""
        panel = self._new_player()
        panel.play_file(url, title, start_position=start_position)
        self.show_view('player')

    def play_playlist(self, tracks, title=None, media_id=None, kind='audiobook',
                      start=None):
        """Play a whole track list (an audiobook folder) as one item."""
        panel = self._new_player()
        panel.play_playlist(tracks, title=title, media_id=media_id, kind=kind,
                            start=start)
        self.show_view('player')

    def play_folder(self, url, title=None, start=None, fallback_tracks=None):
        """Play a folder as an audiobook: list it (which can take a moment on
        a network catalog, so it happens off the UI thread) and hand the whole
        track list to the player, which resumes it where it was left.

        ``fallback_tracks`` is the list saved with a bookmark, used when the
        folder itself can no longer be reached (an offline network catalog),
        so a saved book still opens."""
        name = title or playlist.folder_display_name(url)
        common.speak(_("Loading audiobook: %s") % name)
        channel = common.play_sound('loading', loop=True)

        def work():
            try:
                tracks = playlist.list_folder_tracks(url)
            except Exception as e:
                print(f"[tMedia] audiobook listing failed: {e}")
                tracks = []
            wx.CallAfter(done, tracks)

        def done(tracks):
            common.stop_sound(channel=channel)
            if not tracks:
                tracks = [t for t in (fallback_tracks or []) if t.get('url')]
            if not tracks:
                common.speak(_("No media files in this folder"))
                wx.MessageBox(_("No media files in this folder."),
                              _("Audiobook"), wx.OK | wx.ICON_INFORMATION)
                return
            self.play_playlist(tracks, title=name, media_id=url,
                               kind='audiobook', start=start)

        Thread(target=work, daemon=True).start()

    def _new_player(self):
        self._destroy_player_view()
        panel = PlayerPanel(self.view_container, owner=self)
        self.views['player'] = panel
        self.view_sizer.Add(panel, proportion=1, flag=wx.EXPAND)
        panel.Hide()
        return panel

    def open_settings(self, event):
        settings_window = SettingsWindow(self)
        settings_window.Show()

    def open_bookmarks(self, event=None):
        self.show_view('bookmarks')


if __name__ == '__main__':
    app = wx.App()
    initial_media = sys.argv[1] if len(sys.argv) > 1 else None
    frame = TMediaApp(None, initial_media=initial_media)
    frame.Show()
    app.MainLoop()
