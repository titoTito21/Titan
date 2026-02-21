# TFM/copy_move.py
import wx
import shutil
import threading
import os
from translation import _


class CopyMoveDialog(wx.Dialog):
    def __init__(self, parent, title, max_value):
        wx.Dialog.__init__(self, parent, title=title, size=(400, 150))
        self.panel = wx.Panel(self)
        self.sizer = wx.BoxSizer(wx.VERTICAL)

        self.gauge = wx.Gauge(self.panel, range=max(max_value, 1))
        self.sizer.Add(self.gauge, 0, wx.ALL | wx.EXPAND, 10)

        self.status_text = wx.StaticText(self.panel, label="")
        self.sizer.Add(self.status_text, 0, wx.ALL | wx.EXPAND, 10)

        self.panel.SetSizer(self.sizer)
        self.Layout()
        self.Fit()

    def update(self, value, status):
        """Must be called on the main thread (via wx.CallAfter)."""
        if not self or not self.IsShown():
            return
        try:
            self.gauge.SetValue(value)
            self.status_text.SetLabel(status)
            self.Refresh()
            self.Update()
        except Exception:
            pass


def copy_files_with_progress(parent, src_files, dst_folder):
    """Copy files with a progress dialog. Dialog is created on the calling
    (main) thread; only file I/O runs in the background thread."""
    # Create and show dialog on the main thread
    dialog = CopyMoveDialog(parent, _("Copying files"), len(src_files))
    dialog.Show()

    def copy_thread():
        for i, src in enumerate(src_files):
            dst = os.path.join(dst_folder, os.path.basename(src))
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
                wx.CallAfter(dialog.update, i + 1,
                             _("Copied: {}").format(os.path.basename(src)))
            except Exception as e:
                wx.CallAfter(wx.MessageBox,
                             _("Copy error for {}: {}").format(os.path.basename(src), e),
                             _("Copy Error"), wx.OK | wx.ICON_ERROR)
                wx.CallAfter(dialog.update, i + 1,
                             _("Error copying: {}").format(os.path.basename(src)))

        wx.CallAfter(dialog.Destroy)

    threading.Thread(target=copy_thread, daemon=True).start()


def move_files_with_progress(parent, src_files, dst_folder):
    """Move files with a progress dialog. Dialog is created on the calling
    (main) thread; only file I/O runs in the background thread."""
    # Create and show dialog on the main thread
    dialog = CopyMoveDialog(parent, _("Moving files"), len(src_files))
    dialog.Show()

    def move_thread():
        for i, src in enumerate(src_files):
            dst = os.path.join(dst_folder, os.path.basename(src))
            try:
                shutil.move(src, dst)
                wx.CallAfter(dialog.update, i + 1,
                             _("Moved: {}").format(os.path.basename(src)))
            except Exception as e:
                wx.CallAfter(wx.MessageBox,
                             _("Move error for {}: {}").format(os.path.basename(src), e),
                             _("Move Error"), wx.OK | wx.ICON_ERROR)
                wx.CallAfter(dialog.update, i + 1,
                             _("Error moving: {}").format(os.path.basename(src)))

        wx.CallAfter(dialog.Destroy)

    threading.Thread(target=move_thread, daemon=True).start()
