import wx
import threading
from sound import play_sound

class MenuBar(wx.MenuBar):
    def __init__(self, parent):
        super(MenuBar, self).__init__()

        self.parent = parent

        # Plik menu
        file_menu = wx.Menu()
        settings_item = file_menu.Append(wx.ID_ANY, "Ustawienia...", "Otwórz ustawienia")
        exit_item = file_menu.Append(wx.ID_EXIT, "Wyjście", "Zakończ program")
        self.Append(file_menu, "Plik")

        # Pomoc menu
        help_menu = wx.Menu()
        about_item = help_menu.Append(wx.ID_ABOUT, "O programie", "Informacje o programie")
        self.Append(help_menu, "Pomoc")

        # Bind events
        self.Bind(wx.EVT_MENU, self.on_settings, settings_item)
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        self.Bind(wx.EVT_MENU, self.on_about, about_item)

        # Bind focus and selection events
        self.Bind(wx.EVT_MENU_HIGHLIGHT, self.on_focus)
        self.Bind(wx.EVT_MENU_OPEN, self.on_focus)
        self.Bind(wx.EVT_MENU_CLOSE, self.on_focus)

    def on_settings(self, event):
        play_sound('select.ogg')
        threading.Thread(target=self.open_settings).start()

    def open_settings(self):
        wx.CallAfter(self.show_settings)

    def show_settings(self):
        from settingsgui import SettingsFrame
        settings_frame = SettingsFrame(None, title="Ustawienia")
        settings_frame.Show()

    def on_exit(self, event):
        play_sound('select.ogg')
        self.parent.Close()

    def on_about(self, event):
        play_sound('select.ogg')
        wx.MessageBox("Titan wersja 0.5", "O programie", wx.OK | wx.ICON_INFORMATION)

    def on_focus(self, event):
        play_sound('focus.ogg')
        event.Skip()
