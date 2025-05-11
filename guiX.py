import wx
import os
import platform
import threading
from app_manager import get_applications, open_application
from notifications import get_current_time, get_battery_status, get_volume_level, get_network_status
from sound import initialize_sound, play_focus_sound, play_select_sound, play_statusbar_sound, play_applist_sound, play_endoflist_sound
from menu import MenuBar
from bg5reader import speak

class TitanApp(wx.Frame):
    def __init__(self, *args, version, **kw):
        super(TitanApp, self).__init__(*args, **kw)
        self.version = version
        initialize_sound()
        self.InitUI()
        
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.update_statusbar, self.timer)
        self.timer.Start(5000)  # Aktualizacja co 5 sekund
        
    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        st1 = wx.StaticText(panel, label="(lista aplikacji)")
        vbox.Add(st1, flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)
        
        self.app_listbox = wx.ListBox(panel)
        self.populate_app_list()
        
        vbox.Add(self.app_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=10)
        vbox.Add(wx.StaticText(panel, label="Pasek statusu:"), flag=wx.EXPAND|wx.LEFT|wx.RIGHT|wx.TOP, border=10)

        self.statusbar_listbox = wx.ListBox(panel)
        self.populate_statusbar()
        
        vbox.Add(self.statusbar_listbox, proportion=1, flag=wx.EXPAND|wx.ALL, border=10)
        
        self.app_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_app_selected)
        self.app_listbox.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)
        self.app_listbox.Bind(wx.EVT_MOTION, self.on_focus_change)

        self.statusbar_listbox.Bind(wx.EVT_LISTBOX_DCLICK, self.on_status_selected)
        self.statusbar_listbox.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)
        self.statusbar_listbox.Bind(wx.EVT_MOTION, self.on_focus_change_status)

        panel.SetSizer(vbox)

        # Add the menu bar
        self.SetMenuBar(MenuBar(self))
        
    def populate_app_list(self):
        applications = get_applications()
        for app in applications:
            self.app_listbox.Append(app["name"], app)
    
    def populate_statusbar(self):
        self.statusbar_listbox.Append(f"zegar: {get_current_time()}")
        self.statusbar_listbox.Append(f"poziom baterii: {get_battery_status()}")
        self.statusbar_listbox.Append(f"głośność: {get_volume_level()}")
        self.statusbar_listbox.Append(get_network_status())

    def update_statusbar(self, event):
        self.statusbar_listbox.SetString(0, f"zegar: {get_current_time()}")
        self.statusbar_listbox.SetString(1, f"poziom baterii: {get_battery_status()}")
        self.statusbar_listbox.SetString(2, f"głośność: {get_volume_level()}")
        self.statusbar_listbox.SetString(3, get_network_status())

    def on_app_selected(self, event):
        selection = self.app_listbox.GetSelection()
        if selection != wx.NOT_FOUND:
            app_info = self.app_listbox.GetClientData(selection)
            play_select_sound()
            open_application(app_info)
        
    def on_key_down(self, event):
        keycode = event.GetKeyCode()
        current_focus = self.FindFocus()

        if keycode == wx.WXK_RETURN:
            if current_focus == self.app_listbox:
                self.on_app_selected(event)
            elif current_focus == self.statusbar_listbox:
                self.on_status_selected(event)
        elif keycode == wx.WXK_TAB:
            if current_focus == self.app_listbox:
                self.statusbar_listbox.SetFocus()
                play_statusbar_sound()
            elif current_focus == self.statusbar_listbox:
                self.app_listbox.SetFocus()
                play_applist_sound()
        elif keycode in [wx.WXK_UP, wx.WXK_DOWN]:
            self.on_arrow_key(event)
        else:
            event.Skip()

    def on_arrow_key(self, event):
        keycode = event.GetKeyCode()
        current_focus = self.FindFocus()

        if current_focus == self.app_listbox:
            current_selection = self.app_listbox.GetSelection()
            item_count = self.app_listbox.GetCount()

            if keycode == wx.WXK_UP and current_selection == 0:
                play_endoflist_sound()
            elif keycode == wx.WXK_DOWN and current_selection == item_count - 1:
                play_endoflist_sound()
            else:
                play_focus_sound()

        elif current_focus == self.statusbar_listbox:
            current_selection = self.statusbar_listbox.GetSelection()
            item_count = self.statusbar_listbox.GetCount()

            if keycode == wx.WXK_UP and current_selection == 0:
                play_endoflist_sound()
            elif keycode == wx.WXK_DOWN and current_selection == item_count - 1:
                play_endoflist_sound()
            else:
                play_focus_sound()

        event.Skip()

    def on_focus_change(self, event):
        play_focus_sound()
        event.Skip()

    def on_focus_change_status(self, event):
        play_focus_sound()
        event.Skip()

    def on_status_selected(self, event):
        selection = self.statusbar_listbox.GetSelection()
        if selection != wx.NOT_FOUND:
            play_select_sound()
            status_item = self.statusbar_listbox.GetString(selection)
            threading.Thread(target=self.handle_status_action, args=(status_item,)).start()

    def handle_status_action(self, item):
        if "zegar" in item:
            self.open_time_settings()
        elif "poziom baterii" in item:
            self.open_power_settings()
        elif "głośność" in item:
            self.open_volume_mixer()
        else:
            self.open_network_settings()
    
    def open_time_settings(self):
        if platform.system() == "Windows":
            os.system("timedate.cpl")
        elif platform.system() == "Darwin":
            os.system("open /System/Library/PreferencePanes/DateAndTime.prefPane")
        else:
            wx.MessageBox("Ta funkcja nie jest wspierana na tej platformie.", "Informacja", wx.OK | wx.ICON_INFORMATION)

    def open_power_settings(self):
        if platform.system() == "Windows":
            os.system("powercfg.cpl")
        elif platform.system() == "Darwin":
            os.system("open /System/Library/PreferencePanes/EnergySaver.prefPane")
        else:
            wx.MessageBox("Ta funkcja nie jest wspierana na tej platformie.", "Informacja", wx.OK | wx.ICON_INFORMATION)

    def open_volume_mixer(self):
        if platform.system() == "Windows":
            os.system("sndvol")
        elif platform.system() == "Darwin":
            os.system("open /Applications/Utilities/Audio MIDI Setup.app")
        else:
            wx.MessageBox("Ta funkcja nie jest wspierana na tej platformie.", "Informacja", wx.OK | wx.ICON_INFORMATION)

    def open_network_settings(self):
        if platform.system() == "Windows":
            os.system("ms-settings:network-status")
        elif platform.system() == "Darwin":
            os.system("open /System/Library/PreferencePanes/Network.prefPane")
        else:
            wx.MessageBox("Ta funkcja nie jest wspierana na tej platformie.", "Informacja", wx.OK | wx.ICON_INFORMATION)

if __name__ == "__main__":
    app = wx.App(False)
    frame = TitanApp(None, title="Interfejs graficzny Titana", version="0.2 alpha")
    frame.Show()
    app.MainLoop()
