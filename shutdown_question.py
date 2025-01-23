import wx
from sound import play_sound

class ShutdownDialog(wx.Dialog):
    def __init__(self, *args, **kw):
        super(ShutdownDialog, self).__init__(*args, **kw)
        
        self.InitUI()
        self.SetSize((300, 150))
        self.SetTitle("Potwierdzenie wyjścia")
        self.Centre()
    
    def InitUI(self):
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        question = wx.StaticText(panel, label="Czy na pewno chcesz wyjść z Titana?")
        vbox.Add(question, flag=wx.ALIGN_CENTER | wx.TOP, border=20)
        
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        ok_button = wx.Button(panel, label="OK")
        ok_button.Bind(wx.EVT_BUTTON, self.OnOK)
        hbox.Add(ok_button, flag=wx.RIGHT, border=10)
        
        cancel_button = wx.Button(panel, label="Anuluj")
        cancel_button.Bind(wx.EVT_BUTTON, self.OnCancel)
        hbox.Add(cancel_button)
        
        vbox.Add(hbox, flag=wx.ALIGN_CENTER | wx.TOP, border=20)
        
        panel.SetSizer(vbox)
    
    def OnOK(self, event):
        self.EndModal(wx.ID_OK)
    
    def OnCancel(self, event):
        self.EndModal(wx.ID_CANCEL)

def show_shutdown_dialog():
    play_sound('statusbar.ogg')
    dialog = ShutdownDialog(None)
    result = dialog.ShowModal()
    dialog.Destroy()
    play_sound('applist.ogg')
    return result
