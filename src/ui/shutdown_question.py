import wx
from src.titan_core.sound import play_sound
from src.titan_core.translation import set_language
from src.settings.settings import get_setting

# Get the translation function
_ = set_language(get_setting('language', 'pl'))

def show_shutdown_dialog():
    play_sound('ui/statusbar.ogg')
    dialog = wx.MessageDialog(
        None,
        _("Are you sure you want to exit Titan?"),
        _("Confirm Exit"),
        wx.OK | wx.CANCEL | wx.ICON_QUESTION
    )
    result = dialog.ShowModal()
    dialog.Destroy()
    play_sound('ui/applist.ogg')
    return result
