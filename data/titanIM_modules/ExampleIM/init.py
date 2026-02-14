"""Example Titan IM module.

Demonstrates the unified Sound API that is automatically injected
by the module manager. All external IM modules receive a 'sounds'
object with the same TitanNet/Titan IM sounds.

To enable this module, set status = 0 in __im.TCE.
"""
import sys

# The 'sounds' object is injected by im_module_manager before this code runs.
# Access it via the module reference:
_module = sys.modules[__name__]


def open(parent_frame):
    """Open the communicator window."""
    try:
        import wx

        sounds = _module.sounds

        # Play welcome sound (same as Telegram, EltenLink, Titan-Net)
        sounds.welcome()

        # Show example dialog
        dlg = wx.Dialog(parent_frame, title="Example IM", size=(400, 300))
        sizer = wx.BoxSizer(wx.VERTICAL)

        info = wx.StaticText(dlg, label="Example IM module with unified sounds")
        sizer.Add(info, 0, wx.ALL, 10)

        # Demo buttons for sound API
        btn_msg = wx.Button(dlg, label="New Message Sound")
        btn_sent = wx.Button(dlg, label="Message Sent Sound")
        btn_online = wx.Button(dlg, label="User Online Sound")
        btn_offline = wx.Button(dlg, label="User Offline Sound")
        btn_error = wx.Button(dlg, label="Error Notification")
        btn_success = wx.Button(dlg, label="Success Notification")
        btn_close = wx.Button(dlg, wx.ID_CLOSE, label="Close")

        for btn in [btn_msg, btn_sent, btn_online, btn_offline, btn_error, btn_success, btn_close]:
            sizer.Add(btn, 0, wx.ALL | wx.EXPAND, 5)

        btn_msg.Bind(wx.EVT_BUTTON, lambda e: sounds.new_message())
        btn_sent.Bind(wx.EVT_BUTTON, lambda e: sounds.message_sent())
        btn_online.Bind(wx.EVT_BUTTON, lambda e: sounds.user_online())
        btn_offline.Bind(wx.EVT_BUTTON, lambda e: sounds.user_offline())
        btn_error.Bind(wx.EVT_BUTTON, lambda e: sounds.notify("Connection failed!", 'error'))
        btn_success.Bind(wx.EVT_BUTTON, lambda e: sounds.notify("Connected successfully!", 'success'))
        btn_close.Bind(wx.EVT_BUTTON, lambda e: (sounds.goodbye(), dlg.Close()))

        dlg.SetSizer(sizer)
        sounds.dialog_open()
        dlg.ShowModal()
        dlg.Destroy()

    except Exception as e:
        print(f"[ExampleIM] Error: {e}")


def get_status_text():
    """Return status suffix string."""
    return ""
