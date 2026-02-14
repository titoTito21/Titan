import wx
from translation import _

class MenuBar(wx.MenuBar):
    def __init__(self, parent):
        super().__init__()

        # File Menu
        file_menu = wx.Menu()
        settings_id = wx.NewId()
        exit_id = wx.NewId()

        file_menu.Append(settings_id, _("Client Settings...") + '\tCtrl+K')
        file_menu.AppendSeparator()
        file_menu.Append(exit_id, _("Exit") + '\tAlt+F4')

        self.Append(file_menu, _("File"))

        parent.Bind(wx.EVT_MENU, parent.OnClientSettings, id=settings_id)
        parent.Bind(wx.EVT_MENU, lambda e: parent.Close(), id=exit_id)

        # Voice Menu
        voice_menu = wx.Menu()
        voice_manager_id = wx.NewId()
        voice_clone_id = wx.NewId()
        voice_db_id = wx.NewId()

        voice_menu.Append(voice_manager_id, _("Voice Manager...") + '\tCtrl+M')
        voice_menu.Append(voice_clone_id, _("Clone Voice...") + '\tCtrl+C')
        voice_menu.Append(voice_db_id, _("Voice Database...") + '\tCtrl+D')

        self.Append(voice_menu, _("Voices"))

        parent.Bind(wx.EVT_MENU, parent.OnVoiceManager, id=voice_manager_id)
        parent.Bind(wx.EVT_MENU, parent.OnVoiceCloning, id=voice_clone_id)
        parent.Bind(wx.EVT_MENU, parent.OnVoiceDatabase, id=voice_db_id)

        # Tools Menu
        tools_menu = wx.Menu()
        history_id = wx.NewId()
        cache_id = wx.NewId()
        s2s_id = wx.NewId()
        sound_id = wx.NewId()

        tools_menu.Append(history_id, _("Generation History...") + '\tCtrl+H')
        tools_menu.Append(cache_id, _("Local Cache...") + '\tCtrl+Shift+C')
        tools_menu.AppendSeparator()
        tools_menu.Append(s2s_id, _("Speech to Speech...") + '\tCtrl+S')
        tools_menu.Append(sound_id, _("Sound Effects...") + '\tCtrl+E')

        self.Append(tools_menu, _("Tools"))

        parent.Bind(wx.EVT_MENU, parent.OnHistory, id=history_id)
        parent.Bind(wx.EVT_MENU, parent.OnCacheViewer, id=cache_id)
        parent.Bind(wx.EVT_MENU, parent.OnSpeechToSpeech, id=s2s_id)
        parent.Bind(wx.EVT_MENU, parent.OnSoundEffects, id=sound_id)

        # Account Menu
        account_menu = wx.Menu()
        user_info_id = wx.NewId()
        models_id = wx.NewId()

        account_menu.Append(user_info_id, _("User Info & Subscription...") + '\tCtrl+U')
        account_menu.Append(models_id, _("Available Models...") + '\tCtrl+L')

        self.Append(account_menu, _("Account"))

        parent.Bind(wx.EVT_MENU, parent.OnUserInfo, id=user_info_id)
        parent.Bind(wx.EVT_MENU, parent.OnModels, id=models_id)
