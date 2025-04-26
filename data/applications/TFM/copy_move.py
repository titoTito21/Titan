# TFM/copy_move.py
import wx
import shutil
import threading
import os # Added import

class CopyMoveDialog(wx.Dialog):
    def __init__(self, parent, title, max_value):
        # Pass parent to the wx.Dialog constructor
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

def copy_files_with_progress(parent, src_files, dst_folder): # Added parent parameter
    def copy_thread():
        dialog = CopyMoveDialog(parent, "Kopiowanie plików", len(src_files)) # Pass parent
        dialog.Show()

        for i, src in enumerate(src_files):
            dst = os.path.join(dst_folder, os.path.basename(src))
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                wx.CallAfter(dialog.update, i + 1, f"Skopiowano: {os.path.basename(src)}")
            except Exception as e:
                wx.CallAfter(wx.MessageBox, f"Błąd kopiowania {os.path.basename(src)}: {e}", "Błąd Kopiowania", wx.OK | wx.ICON_ERROR)
                wx.CallAfter(dialog.update, i + 1, f"Błąd kopiowania: {os.path.basename(src)}")


        wx.CallAfter(dialog.Destroy)

    threading.Thread(target=copy_thread).start()

def move_files_with_progress(parent, src_files, dst_folder): # Added parent parameter
    def move_thread():
        dialog = CopyMoveDialog(parent, "Przenoszenie plików", len(src_files)) # Pass parent
        dialog.Show()

        for i, src in enumerate(src_files):
            dst = os.path.join(dst_folder, os.path.basename(src))
            try:
                shutil.move(src, dst)
                wx.CallAfter(dialog.update, i + 1, f"Przeniesiono: {os.path.basename(src)}")
            except Exception as e:
                wx.CallAfter(wx.MessageBox, f"Błąd przenoszenia {os.path.basename(src)}: {e}", "Błąd Przenoszenia", wx.OK | wx.ICON_ERROR)
                wx.CallAfter(dialog.update, i + 1, f"Błąd przenoszenia: {os.path.basename(src)}")

        wx.CallAfter(dialog.Destroy)

    threading.Thread(target=move_thread).start()