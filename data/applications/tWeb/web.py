# -*- coding: utf-8 -*-
import wx
import wx.html2
import re
import requests
from translation import _

from common import _apply_skin_to_tree, config, save_config
from browser_tab import BrowserTab
from downloads import DownloadManager, DownloadsDialog
from history import HistoryStore, HistoryDialog
from bookmarks import BookmarkStore, BookmarksDialog
from findbar import FindBar


class BrowserFrame(wx.Frame):
    def __init__(self, *args, **kwargs):
        super(BrowserFrame, self).__init__(*args, **kwargs)

        self.settings = config
        self.home_url = 'https://titosofttitan.com/titan'

        self.download_manager = DownloadManager(self)
        self.history_store = HistoryStore()
        self.bookmark_store = BookmarkStore()
        self.tabs = []

        self.loading = False
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.OnTimer)

        self.InitUI()
        self.Centre()
        self.Show()
        self.open_new_tab(self.home_url)

    # ==================================================================== #
    # UI construction
    # ==================================================================== #
    def InitUI(self):
        self.SetTitle(_("tBrowser"))
        self.SetSize((900, 650))

        self.panel = wx.Panel(self)
        self.panel.SetWindowStyleFlag(wx.TAB_TRAVERSAL)

        vbox = wx.BoxSizer(wx.VERTICAL)

        self.toolbar = wx.Panel(self.panel)
        self.toolbar_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.back_button = wx.Button(self.toolbar, label=_("Wstecz"))
        self.forward_button = wx.Button(self.toolbar, label=_("Dalej"))
        self.refresh_button = wx.Button(self.toolbar, label=_("Odśwież"))
        # Full text labels rather than a bare glyph: a screen reader reads a
        # button's own caption as its accessible name, and "☆" alone reads as
        # a Unicode character name, not "add bookmark".
        self.star_button = wx.Button(self.toolbar, label=_("Dodaj zakładkę"))

        self.back_button.SetToolTip(_("Przycisk Wstecz"))
        self.forward_button.SetToolTip(_("Przycisk Dalej"))
        self.refresh_button.SetToolTip(_("Przycisk Odśwież"))

        self.address = wx.TextCtrl(self.toolbar, style=wx.TE_PROCESS_ENTER)
        self.address.SetHint(_("Wpisz adres lub wyszukaj w Google"))

        self.zoom_out_button = wx.Button(self.toolbar, label=_("Pomniejsz"))
        self.zoom_reset_button = wx.Button(self.toolbar, label=_("100%"))
        self.zoom_in_button = wx.Button(self.toolbar, label=_("Powiększ"))
        self.zoom_reset_button.SetToolTip(_("Resetuj powiększenie"))

        self.new_tab_button = wx.Button(self.toolbar, label=_("Nowa karta"))

        self.toolbar_sizer.Add(self.back_button, 0, wx.ALL, 5)
        self.toolbar_sizer.Add(self.forward_button, 0, wx.ALL, 5)
        self.toolbar_sizer.Add(self.refresh_button, 0, wx.ALL, 5)
        self.toolbar_sizer.Add(self.star_button, 0, wx.ALL, 5)
        self.toolbar_sizer.Add(self.address, 1, wx.ALL | wx.EXPAND, 5)
        self.toolbar_sizer.Add(self.zoom_out_button, 0, wx.ALL, 5)
        self.toolbar_sizer.Add(self.zoom_reset_button, 0, wx.ALL, 5)
        self.toolbar_sizer.Add(self.zoom_in_button, 0, wx.ALL, 5)
        self.toolbar_sizer.Add(self.new_tab_button, 0, wx.ALL, 5)

        self.toolbar.SetSizer(self.toolbar_sizer)
        vbox.Add(self.toolbar, 0, wx.EXPAND)

        self.notebook = wx.Notebook(self.panel)
        vbox.Add(self.notebook, 1, wx.EXPAND)

        self.findbar = FindBar(self.panel, self.get_active_tab)
        vbox.Add(self.findbar, 0, wx.EXPAND)

        self.panel.SetSizer(vbox)

        self.statusbar = self.CreateStatusBar(2)
        self.statusbar.SetStatusWidths([-1, 100])

        self.progress = wx.Gauge(self.statusbar, range=100, style=wx.GA_HORIZONTAL)
        self.Bind(wx.EVT_SIZE, self.OnSize)
        self.OnSize(None)

        self.BindEvents()
        self.CreateMenuBar()
        _apply_skin_to_tree(self)

    def OnSize(self, event):
        rect = self.statusbar.GetFieldRect(1)
        self.progress.SetPosition((rect.x + 2, rect.y + 2))
        self.progress.SetSize((rect.width - 4, rect.height - 4))
        if event:
            event.Skip()

    def BindEvents(self):
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.OnTabChanged)

        self.address.Bind(wx.EVT_TEXT_ENTER, self.OnAddressEnter)
        self.back_button.Bind(wx.EVT_BUTTON, lambda e: self._active_call('go_back'))
        self.forward_button.Bind(wx.EVT_BUTTON, lambda e: self._active_call('go_forward'))
        self.refresh_button.Bind(wx.EVT_BUTTON, lambda e: self._active_call('refresh'))
        self.star_button.Bind(wx.EVT_BUTTON, self.OnToggleBookmark)
        self.zoom_out_button.Bind(wx.EVT_BUTTON, lambda e: self._active_call('zoom_out'))
        self.zoom_reset_button.Bind(wx.EVT_BUTTON, lambda e: self._active_call('zoom_reset'))
        self.zoom_in_button.Bind(wx.EVT_BUTTON, lambda e: self._active_call('zoom_in'))
        self.new_tab_button.Bind(wx.EVT_BUTTON, lambda e: self.open_new_tab())

        self.Bind(wx.EVT_CHAR_HOOK, self.OnCharHook)

        # Accelerator table so shortcuts work even when a WebView (Edge) tab has focus.
        ids = {name: wx.NewIdRef() for name in (
            'address', 'refresh', 'downloads', 'new_tab', 'close_tab',
            'next_tab', 'prev_tab', 'history', 'bookmarks', 'toggle_bookmark',
            'find', 'find_next', 'find_prev', 'zoom_in', 'zoom_out', 'zoom_reset',
        )}
        self._accel_ids = ids
        accel_entries = [
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('L'), ids['address']),
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F6, ids['address']),
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F5, ids['refresh']),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('J'), ids['downloads']),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('T'), ids['new_tab']),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('W'), ids['close_tab']),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, wx.WXK_TAB, ids['next_tab']),
            wx.AcceleratorEntry(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, wx.WXK_TAB, ids['prev_tab']),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('H'), ids['history']),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('B'), ids['bookmarks']),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('D'), ids['toggle_bookmark']),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('F'), ids['find']),
            wx.AcceleratorEntry(wx.ACCEL_NORMAL, wx.WXK_F3, ids['find_next']),
            wx.AcceleratorEntry(wx.ACCEL_SHIFT, wx.WXK_F3, ids['find_prev']),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('='), ids['zoom_in']),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, wx.WXK_ADD, ids['zoom_in']),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('-'), ids['zoom_out']),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, wx.WXK_SUBTRACT, ids['zoom_out']),
            wx.AcceleratorEntry(wx.ACCEL_CTRL, ord('0'), ids['zoom_reset']),
        ]
        self.SetAcceleratorTable(wx.AcceleratorTable(accel_entries))
        self.Bind(wx.EVT_MENU, lambda e: self.focus_address(), id=ids['address'])
        self.Bind(wx.EVT_MENU, lambda e: self._active_call('refresh'), id=ids['refresh'])
        self.Bind(wx.EVT_MENU, lambda e: self.ShowDownloads(), id=ids['downloads'])
        self.Bind(wx.EVT_MENU, lambda e: self.open_new_tab(), id=ids['new_tab'])
        self.Bind(wx.EVT_MENU, lambda e: self.close_tab(), id=ids['close_tab'])
        self.Bind(wx.EVT_MENU, lambda e: self._cycle_tab(1), id=ids['next_tab'])
        self.Bind(wx.EVT_MENU, lambda e: self._cycle_tab(-1), id=ids['prev_tab'])
        self.Bind(wx.EVT_MENU, lambda e: self.ShowHistory(), id=ids['history'])
        self.Bind(wx.EVT_MENU, lambda e: self.ShowBookmarks(), id=ids['bookmarks'])
        self.Bind(wx.EVT_MENU, self.OnToggleBookmark, id=ids['toggle_bookmark'])
        self.Bind(wx.EVT_MENU, lambda e: self.findbar.OpenBar(), id=ids['find'])
        self.Bind(wx.EVT_MENU, lambda e: self.findbar.find_next(), id=ids['find_next'])
        self.Bind(wx.EVT_MENU, lambda e: self.findbar.find_previous(), id=ids['find_prev'])
        self.Bind(wx.EVT_MENU, lambda e: self._active_call('zoom_in'), id=ids['zoom_in'])
        self.Bind(wx.EVT_MENU, lambda e: self._active_call('zoom_out'), id=ids['zoom_out'])
        self.Bind(wx.EVT_MENU, lambda e: self._active_call('zoom_reset'), id=ids['zoom_reset'])

    def CreateMenuBar(self):
        menubar = wx.MenuBar()
        app_menu = wx.Menu()

        new_tab_item = app_menu.Append(wx.ID_ANY, _("Nowa karta\tCtrl+T"))
        close_tab_item = app_menu.Append(wx.ID_ANY, _("Zamknij kartę\tCtrl+W"))
        app_menu.AppendSeparator()
        history_item = app_menu.Append(wx.ID_ANY, _("Historia...\tCtrl+H"))
        bookmarks_item = app_menu.Append(wx.ID_ANY, _("Zakładki...\tCtrl+B"))
        downloads_item = app_menu.Append(wx.ID_ANY, _("Pobrane pliki...\tCtrl+J"))
        app_menu.AppendSeparator()
        settings_item = app_menu.Append(wx.ID_ANY, _("Ustawienia..."))
        menubar.Append(app_menu, _("Aplikacja"))

        self.SetMenuBar(menubar)
        self.Bind(wx.EVT_MENU, lambda e: self.open_new_tab(), new_tab_item)
        self.Bind(wx.EVT_MENU, lambda e: self.close_tab(), close_tab_item)
        self.Bind(wx.EVT_MENU, lambda e: self.ShowHistory(), history_item)
        self.Bind(wx.EVT_MENU, lambda e: self.ShowBookmarks(), bookmarks_item)
        self.Bind(wx.EVT_MENU, lambda e: self.ShowDownloads(), downloads_item)
        self.Bind(wx.EVT_MENU, self.OnSettings, settings_item)

    # ==================================================================== #
    # Tab management
    # ==================================================================== #
    def get_active_tab(self):
        if not self.tabs:
            return None
        idx = self.notebook.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self.tabs):
            return None
        return self.tabs[idx]

    def open_new_tab(self, url=None):
        tab = BrowserTab(self.notebook, self)
        self.tabs.append(tab)
        self.notebook.AddPage(tab, self._short_title(tab.current_title))
        self.notebook.SetSelection(len(self.tabs) - 1)
        self.notify_tab_changed(tab)
        tab.load(url or self.home_url)
        tab.focus_content()
        return tab

    def close_tab(self, tab=None):
        tab = tab or self.get_active_tab()
        if tab is None or tab not in self.tabs:
            return
        idx = self.tabs.index(tab)
        del self.tabs[idx]
        self.notebook.DeletePage(idx)
        if not self.tabs:
            self.Close()
        else:
            new_tab = self.get_active_tab()
            if new_tab is not None:
                self.notify_tab_changed(new_tab)

    def _cycle_tab(self, delta):
        if len(self.tabs) < 2:
            return
        idx = (self.notebook.GetSelection() + delta) % len(self.tabs)
        self.notebook.SetSelection(idx)

    def _active_call(self, method_name):
        tab = self.get_active_tab()
        if tab is not None:
            getattr(tab, method_name)()
        if method_name in ('zoom_in', 'zoom_out', 'zoom_reset'):
            self.update_zoom_display()

    def OnTabChanged(self, event):
        tab = self.get_active_tab()
        if tab is not None:
            self.notify_tab_changed(tab)
            self.set_loading_state(tab.loading)
        event.Skip()

    def _short_title(self, title):
        title = title or _("Nowa karta")
        return title if len(title) <= 24 else title[:21] + '...'

    def notify_tab_changed(self, tab):
        """A tab's title/url changed, or it became the active tab."""
        if tab in self.tabs:
            idx = self.tabs.index(tab)
            self.notebook.SetPageText(idx, self._short_title(tab.get_title()))
        if tab is not self.get_active_tab():
            return
        self.address.SetValue(tab.get_url())
        self.SetTitle("{} - tBrowser".format(tab.get_title()))
        self.back_button.Enable(tab.can_go_back())
        self.forward_button.Enable(tab.can_go_forward())
        self.update_bookmark_star()
        self.update_zoom_display()

    # ==================================================================== #
    # Loading / status bar (driven by the active tab only)
    # ==================================================================== #
    def set_loading_state(self, is_loading):
        self.loading = is_loading
        if is_loading:
            self.statusbar.SetStatusText(_("Ładowanie strony..."))
            self.progress.SetValue(0)
            self.timer.Start(100)
        else:
            self.statusbar.SetStatusText(_("Strona załadowana."))
            self.progress.SetValue(100)
            self.timer.Stop()

    def OnTimer(self, event):
        if self.loading:
            current_value = self.progress.GetValue()
            if current_value < 90:
                self.progress.SetValue(current_value + 5)
        else:
            self.timer.Stop()

    def notify_download_started(self, url):
        self.statusbar.SetStatusText(_("Pobieranie: {}").format(url))

    # ==================================================================== #
    # Address bar / navigation
    # ==================================================================== #
    def focus_address(self):
        self.address.SetFocus()
        self.address.SelectAll()

    def OnAddressEnter(self, event):
        input_text = self.address.GetValue().strip()
        if not input_text:
            return
        if self.is_probable_url(input_text):
            url = input_text
            if not url.startswith(('http://', 'https://')):
                url = 'http://' + url
            self.address.SetValue(url)
        else:
            query = requests.utils.quote(input_text)
            url = "https://www.google.com/search?q={}".format(query)
            self.address.SetValue(url)

        tab = self.get_active_tab() or self.open_new_tab()
        tab.load(url)

    def open_url_in_active_tab(self, url):
        tab = self.get_active_tab() or self.open_new_tab()
        tab.load(url)

    def is_probable_url(self, text):
        return bool(re.match(r'^[\w.-]+\.[a-z]{2,}$', text, re.IGNORECASE))

    # ==================================================================== #
    # Bookmarks / history / downloads dialogs
    # ==================================================================== #
    def update_bookmark_star(self):
        tab = self.get_active_tab()
        if tab is None:
            return
        marked = self.bookmark_store.is_bookmarked(tab.get_url())
        self.star_button.SetLabel(_("Usuń zakładkę") if marked else _("Dodaj zakładkę"))

    def update_zoom_display(self):
        tab = self.get_active_tab()
        can_zoom = tab is not None and tab.is_zoom_ready()
        self.zoom_out_button.Enable(can_zoom)
        self.zoom_in_button.Enable(can_zoom)
        self.zoom_reset_button.Enable(can_zoom)
        if not can_zoom:
            self.zoom_reset_button.SetLabel(_("100%"))
            return
        try:
            factor = tab.browser.GetZoomFactor()
        except Exception:
            factor = 1.0
        self.zoom_reset_button.SetLabel("{}%".format(int(round(factor * 100))))

    def OnToggleBookmark(self, event):
        tab = self.get_active_tab()
        if tab is None:
            return
        self.bookmark_store.toggle(tab.get_url(), tab.get_title())
        self.update_bookmark_star()

    def ShowBookmarks(self):
        dlg = BookmarksDialog(self, self.bookmark_store, self.open_url_in_active_tab)
        dlg.ShowModal()
        dlg.Destroy()
        self.update_bookmark_star()

    def ShowHistory(self):
        dlg = HistoryDialog(self, self.history_store, self.open_url_in_active_tab)
        dlg.ShowModal()
        dlg.Destroy()

    def ShowDownloads(self):
        dlg = DownloadsDialog(self, self.download_manager)
        dlg.ShowModal()
        dlg.Destroy()

    # ==================================================================== #
    # Global keyboard handling
    # ==================================================================== #
    def OnCharHook(self, event):
        """Frame-wide handling that must work regardless of which child has
        focus (toolbar, notebook, address bar).

        Deliberately does NOT swallow a bare Alt tap here: that would block
        the standard Windows Alt-focuses-the-menu-bar convention (needed for
        keyboard/screen-reader users) from anywhere in the window. The
        WebView2-freeze fix for Alt (see browser_tab.OnBrowserCharHook) only
        needs to apply while focus is actually inside the WebView2 render
        area, which that handler already scopes correctly -- it fires first
        and swallows the event before it would ever reach here."""
        keycode = event.GetKeyCode()

        if keycode == wx.WXK_ESCAPE and self.findbar.IsShown():
            self.findbar.CloseBar()
        else:
            event.Skip()

    # ==================================================================== #
    # Settings dialog
    # ==================================================================== #
    def OnSettings(self, event):
        settings_dialog = SettingsDialog(self)
        settings_dialog.ShowModal()
        settings_dialog.Destroy()


class SettingsDialog(wx.Dialog):
    def __init__(self, parent):
        super(SettingsDialog, self).__init__(parent, title=_("Ustawienia tBrowser"))
        self.settings = config

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Grupa "Oznajmianie"
        announcement_box = wx.StaticBox(panel, label=_("Oznajmianie"))
        announcement_sizer = wx.StaticBoxSizer(announcement_box, wx.VERTICAL)

        self.announce_summary_cb = wx.CheckBox(panel, label=_("Oznajmiaj podsumowanie strony"))
        self.announce_summary_cb.SetValue(self.settings.getboolean('announcements', 'announce_page_summary'))

        self.loading_messages_cb = wx.CheckBox(panel, label=_("Komunikaty o ładowaniu strony"))
        self.loading_messages_cb.SetValue(self.settings.getboolean('announcements', 'loading_messages'))

        announcement_sizer.Add(self.announce_summary_cb, flag=wx.ALL, border=5)
        announcement_sizer.Add(self.loading_messages_cb, flag=wx.ALL, border=5)

        # Grupa "Interfejs"
        interface_box = wx.StaticBox(panel, label=_("Interfejs"))
        interface_sizer = wx.StaticBoxSizer(interface_box, wx.VERTICAL)

        view_mode_label = wx.StaticText(panel, label=_("Wybierz tryb przeglądania strony:"))
        self.view_mode_choice = wx.Choice(panel,
            choices=[_("Widok sieciowy (edge)"), _("Tryb wirtualnego bufora")])
        current_mode = self.settings['interface'].get('view_mode', 'edge')
        if current_mode == 'edge':
            self.view_mode_choice.SetSelection(0)
        else:
            self.view_mode_choice.SetSelection(1)

        interface_sizer.Add(view_mode_label, flag=wx.ALL, border=5)
        interface_sizer.Add(self.view_mode_choice, flag=wx.ALL | wx.EXPAND, border=5)

        # Grupa "Prywatność"
        privacy_box = wx.StaticBox(panel, label=_("Prywatność"))
        privacy_sizer = wx.StaticBoxSizer(privacy_box, wx.VERTICAL)

        self.block_cookies_cb = wx.CheckBox(panel, label=_("Nie wyświetlaj alertów o plikach cookie (o ile to możliwe)"))
        self.block_cookies_cb.SetValue(self.settings.getboolean('privacy', 'block_cookie_banners'))

        privacy_sizer.Add(self.block_cookies_cb, flag=wx.ALL, border=5)

        # Przyciski Zapisz i Anuluj
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        save_btn = wx.Button(panel, label=_("Zapisz"))
        cancel_btn = wx.Button(panel, label=_("Anuluj"))
        btn_sizer.Add(save_btn, flag=wx.ALL, border=5)
        btn_sizer.Add(cancel_btn, flag=wx.ALL, border=5)

        save_btn.Bind(wx.EVT_BUTTON, self.OnSave)
        cancel_btn.Bind(wx.EVT_BUTTON, self.OnCancel)

        vbox.Add(announcement_sizer, flag=wx.ALL | wx.EXPAND, border=10)
        vbox.Add(interface_sizer, flag=wx.ALL | wx.EXPAND, border=10)
        vbox.Add(privacy_sizer, flag=wx.ALL | wx.EXPAND, border=10)
        vbox.Add(btn_sizer, flag=wx.ALIGN_CENTER)

        panel.SetSizer(vbox)
        self.SetSize((400, 420))
        self.Centre()
        _apply_skin_to_tree(self)

    def OnSave(self, event):
        self.settings['announcements']['announce_page_summary'] = str(self.announce_summary_cb.GetValue())
        self.settings['announcements']['loading_messages'] = str(self.loading_messages_cb.GetValue())

        if self.view_mode_choice.GetSelection() == 0:
            self.settings['interface']['view_mode'] = 'edge'
        else:
            self.settings['interface']['view_mode'] = 'virtual_buffer'

        self.settings['privacy']['block_cookie_banners'] = str(self.block_cookies_cb.GetValue())

        save_config()

        wx.MessageBox(
            _("Ustawienia zostały zapisane. Tryb przeglądania zostanie zastosowany dla nowo otwieranych kart; "
              "pozostałe ustawienia obowiązują od razu."),
            _("Informacja"), wx.OK | wx.ICON_INFORMATION)
        self.EndModal(wx.ID_OK)

    def OnCancel(self, event):
        self.EndModal(wx.ID_CANCEL)


if __name__ == '__main__':
    app = wx.App()
    frame = BrowserFrame(None)
    app.MainLoop()
