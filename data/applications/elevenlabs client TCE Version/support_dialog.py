import wx
import webbrowser
from translation import _

class SupportDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Dziękuję za używanie klienta elevenLabs"), size=(400, 200))
        
        vbox = wx.BoxSizer(wx.VERTICAL)
        
        message = _("Jeśli uważasz, że mój program jest przydatny, rozważ wsparcie mnie "
                     "kawą, piwem lub paczką papierosów itp. na utrzymanie kosztów serwera bazy danych.")
        msg_text = wx.StaticText(self, label=message)
        vbox.Add(msg_text, 1, flag=wx.ALL | wx.EXPAND, border=10)
        
        donate_button = wx.Button(self, label=_("Dotacja"))
        donate_button.Bind(wx.EVT_BUTTON, self.on_donate)
        vbox.Add(donate_button, 0, flag=wx.ALL, border=10)
        
        ok_button = wx.Button(self, label=_("OK"))
        ok_button.Bind(wx.EVT_BUTTON, self.on_ok)
        vbox.Add(ok_button, 0, flag=wx.ALL, border=10)

        self.SetSizer(vbox)

    def on_donate(self, event):
        webbrowser.open('https://www.paypal.com/paypalme/tito2x1')
        self.Close()

    def on_ok(self, event):
        self.Close()

if __name__ == "__main__":
    app = wx.App(False)
    dialog = SupportDialog(None)
    dialog.ShowModal()
    app.MainLoop()
