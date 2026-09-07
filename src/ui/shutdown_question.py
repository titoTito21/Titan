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
    # Tell the READER this is a question dialog, so it reads it as one -
    # with the question earcon and the word said a little lower - however
    # the dialog is skinned and whether or not the icon can be detected.
    # Titan Access hears it through its own bridge and NVDA through its
    # add-on; a reader that can do neither simply reads the dialog, which
    # is what happened for every reader but Titan Access until now.
    try:
        from src.accessibility.messages import announce_dialog_kind
        announce_dialog_kind("question")
    except Exception:
        pass
    result = dialog.ShowModal()
    dialog.Destroy()
    play_sound('ui/applist.ogg')
    return result
