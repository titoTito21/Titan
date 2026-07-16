import wx
import sys
from translation import _

import common
from MediaCatalog import MediaCatalogPanel
from Settings import SettingsWindow
from player import PlayerPanel
from YoutubeSearch import YoutubeSearchPanel


class FunctionListPanel(wx.Panel):
    """Root view: pick Media Catalog or YouTube Search."""

    def __init__(self, parent, owner, *args, **kwargs):
        super(FunctionListPanel, self).__init__(parent, *args, **kwargs)
        self.owner = owner

        vbox = wx.BoxSizer(wx.VERTICAL)
        self.function_list = wx.ListBox(self, choices=[_("Media Catalog"), _("YouTube Search")])
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
        settings_item = fileMenu.Append(wx.ID_ANY, _('Settings...'))
        menubar.Append(fileMenu, _('&Application'))
        self.SetMenuBar(menubar)

        self.Bind(wx.EVT_MENU, self.open_settings, settings_item)

        self.show_view('function_list')

        if initial_media:
            self.play_media(initial_media)

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
        if self.current_view == name:
            return
        if self.current_view == 'player' and name != 'player':
            self._destroy_player_view()

        panel = self._get_or_create_view(name)
        for key, existing in self.views.items():
            if existing is not panel:
                existing.Hide()
        panel.Show()

        if push and self.current_view is not None:
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

    def play_media(self, url, title=None):
        """Switch to the embedded player and start playback. This is what
        the media catalog / YouTube search views call instead of opening a
        second top-level Player window."""
        self._destroy_player_view()
        panel = PlayerPanel(self.view_container, owner=self)
        self.views['player'] = panel
        self.view_sizer.Add(panel, proportion=1, flag=wx.EXPAND)
        panel.Hide()
        panel.play_file(url, title)
        self.show_view('player')

    def open_settings(self, event):
        settings_window = SettingsWindow(self)
        settings_window.Show()


if __name__ == '__main__':
    app = wx.App()
    initial_media = sys.argv[1] if len(sys.argv) > 1 else None
    frame = TMediaApp(None, initial_media=initial_media)
    frame.Show()
    app.MainLoop()
