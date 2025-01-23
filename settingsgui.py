import wx
import os
from settings import load_settings, save_settings
from sound import set_theme, initialize_sound, play_sound, resource_path
from tts import speak

SFX_DIR = resource_path('sfx')

class SettingsFrame(wx.Frame):
    def __init__(self, *args, **kw):
        super(SettingsFrame, self).__init__(*args, **kw)

        self.settings = load_settings()
        
        self.InitUI()
        play_sound('sectionchange.ogg')
    
    def InitUI(self):
        panel = wx.Panel(self)
        notebook = wx.Notebook(panel)
        
        # Zakładka dźwięk
        self.sound_panel = wx.Panel(notebook)
        self.general_panel = wx.Panel(notebook)
        
        notebook.AddPage(self.sound_panel, "Dźwięk")
        notebook.AddPage(self.general_panel, "Ogólne")
        
        self.InitSoundPanel()
        self.InitGeneralPanel()
        
        # Dodajemy przyciski na dole
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        save_button = wx.Button(panel, label="Zapisz")
        save_button.Bind(wx.EVT_BUTTON, self.OnSave)
        save_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        save_button.Bind(wx.EVT_BUTTON, self.OnSelect)

        cancel_button = wx.Button(panel, label="Anuluj")
        cancel_button.Bind(wx.EVT_BUTTON, self.OnCancel)
        cancel_button.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        cancel_button.Bind(wx.EVT_BUTTON, self.OnSelect)

        hbox.Add(save_button, flag=wx.RIGHT, border=10)
        hbox.Add(cancel_button, flag=wx.RIGHT, border=10)
        
        vbox = wx.BoxSizer(wx.VERTICAL)
        vbox.Add(notebook, 1, wx.EXPAND | wx.ALL, 10)
        vbox.Add(hbox, flag=wx.ALIGN_RIGHT | wx.ALL, border=10)
        
        panel.SetSizer(vbox)
        
        self.SetSize((400, 300))
        self.SetTitle("Ustawienia")
        self.Centre()
    
    def InitSoundPanel(self):
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        theme_label = wx.StaticText(self.sound_panel, label="Wybierz temat dźwiękowy:")
        vbox.Add(theme_label, flag=wx.LEFT | wx.TOP, border=10)
        
        self.theme_choice = wx.Choice(self.sound_panel)
        self.theme_choice.Bind(wx.EVT_CHOICE, self.OnThemeSelected)
        self.theme_choice.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        
        themes = [d for d in os.listdir(SFX_DIR) if os.path.isdir(os.path.join(SFX_DIR, d))]
        self.theme_choice.AppendItems(themes)
        
        current_theme = self.settings.get('sound', {}).get('theme', 'default')
        if current_theme in themes:
            self.theme_choice.SetStringSelection(current_theme)
        
        vbox.Add(self.theme_choice, flag=wx.LEFT | wx.EXPAND, border=10)
        
        self.sound_panel.SetSizer(vbox)
    
    def InitGeneralPanel(self):
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        self.quick_start_cb = wx.CheckBox(self.general_panel, label="Szybki start")
        self.quick_start_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.quick_start_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        quick_start_value = self.settings.get('general', {}).get('quick_start', 'False')
        self.quick_start_cb.SetValue(quick_start_value.lower() in ['true', '1'])
        vbox.Add(self.quick_start_cb, flag=wx.LEFT | wx.TOP, border=10)
        
        self.confirm_exit_cb = wx.CheckBox(self.general_panel, label="Potwierdź wyjście z Titana")
        self.confirm_exit_cb.Bind(wx.EVT_SET_FOCUS, self.OnFocus)
        self.confirm_exit_cb.Bind(wx.EVT_CHECKBOX, self.OnCheckBox)
        confirm_exit_value = self.settings.get('general', {}).get('confirm_exit', 'False')
        self.confirm_exit_cb.SetValue(confirm_exit_value.lower() in ['true', '1'])
        vbox.Add(self.confirm_exit_cb, flag=wx.LEFT | wx.TOP, border=10)
        
        self.general_panel.SetSizer(vbox)
    
    def OnThemeSelected(self, event):
        theme = self.theme_choice.GetStringSelection()
        set_theme(theme)
        initialize_sound()
    
    def OnSave(self, event):
        self.settings['sound'] = {'theme': self.theme_choice.GetStringSelection()}
        self.settings['general'] = {
            'quick_start': str(self.quick_start_cb.GetValue()),
            'confirm_exit': str(self.confirm_exit_cb.GetValue())
        }
        save_settings(self.settings)
        speak('Ustawienia zostały zapisane')
        self.Close()

    def OnCancel(self, event):
        self.Close()

    def OnFocus(self, event):
        play_sound('focus.ogg')
        event.Skip()

    def OnSelect(self, event):
        play_sound('select.ogg')
        event.Skip()

    def OnCheckBox(self, event):
        if event.IsChecked():
            play_sound('x.ogg')
        else:
            play_sound('focus.ogg')
        event.Skip()
