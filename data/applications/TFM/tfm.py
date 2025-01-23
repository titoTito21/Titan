import wx
from gui import FileManager

def main():
    app = wx.App(False)
    frame = FileManager()
    frame.Show()
    app.MainLoop()

if __name__ == "__main__":
    main()
