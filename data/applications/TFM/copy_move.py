import wx
import shutil
import threading

class CopyMoveDialog(wx.Dialog):
    def __init__(self, parent, title, max_value):
        wx.Dialog.__init__(self, parent, title=title, size=(400, 150))
        self.panel = wx.Panel(self)
        self.sizer = wx.BoxSizer(wx.VERTICAL)

        self.gauge = wx.Gauge(self.panel, range=max_value)
        self.sizer.Add(self.gauge, 0, wx.ALL | wx.EXPAND, 10)

        self.status_text = wx.StaticText(self.panel, label="")
        self.sizer.Add(self.status_text, 0, wx.ALL | wx.EXPAND, 10)

        self.panel.SetSizer(self.sizer)
        self.Layout()
        self.Fit()

    def update(self, value, status):
        self.gauge.SetValue(value)
        self.status_text.SetLabel(status)
        self.Refresh()
        self.Update()

def copy_files_with_progress(src_files, dst_folder):
    def copy_thread():
        dialog = CopyMoveDialog(None, "Kopiowanie plików", len(src_files))
        dialog.Show()

        for i, src in enumerate(src_files):
            dst = os.path.join(dst_folder, os.path.basename(src))
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            wx.CallAfter(dialog.update, i + 1, f"Kopiowanie {src} do {dst}")

        wx.CallAfter(dialog.Destroy)

    threading.Thread(target=copy_thread).start()

def move_files_with_progress(src_files, dst_folder):
    def move_thread():
        dialog = CopyMoveDialog(None, "Przenoszenie plików", len(src_files))
        dialog.Show()

        for i, src in enumerate(src_files):
            dst = os.path.join(dst_folder, os.path.basename(src))
            shutil.move(src, dst)
            wx.CallAfter(dialog.update, i + 1, f"Przenoszenie {src} do {dst}")

        wx.CallAfter(dialog.Destroy)

    threading.Thread(target=move_thread).start()
