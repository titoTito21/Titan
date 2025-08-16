import wx
from translation import _

class MenuBar(wx.MenuBar):
    def __init__(self, parent):
        super().__init__()

        # Dodanie menu Klient
        client_menu = wx.Menu()

        # Opcje w menu Klient
        settings_id = wx.NewId()
        voice_db_id = wx.NewId()
        voice_clone_id = wx.NewId()

        client_menu.Append(settings_id, _("Ustawienia klienta...") + '\tCtrl+K')
        client_menu.Append(voice_db_id, _("Baza danych głosów...") + '\tCtrl+D')
        client_menu.Append(voice_clone_id, _("Klonowanie głosu...") + '\tCtrl+C')
        
        self.Append(client_menu, _("Klient"))

        # Połączenie opcji z metodami
        parent.Bind(wx.EVT_MENU, parent.OnClientSettings, id=settings_id)
        parent.Bind(wx.EVT_MENU, parent.OnVoiceDatabase, id=voice_db_id)
        parent.Bind(wx.EVT_MENU, parent.OnVoiceCloning, id=voice_clone_id)
