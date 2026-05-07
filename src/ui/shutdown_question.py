import wx
from src.titan_core.sound import play_sound
from src.titan_core.translation import set_language
from src.settings.settings import get_setting
from src.titan_core.skin_manager import apply_skin_to_window

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
    try:
        apply_skin_to_window(dialog)
    except Exception:
        pass
    result = dialog.ShowModal()
    dialog.Destroy()
    play_sound('ui/applist.ogg')
    return result
