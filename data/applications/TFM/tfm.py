# TFM/tfm.py
import wx
import os
from translation import _


# Now, import the rest of the application modules
from gui import FileManager
from sound import initialize_sound, play_startup_sound # Import initialize_sound and play_startup_sound

def main():
    app = wx.App(False)
    # Initialize sound after wx.App is created, especially if using wx.StandardPaths
    initialize_sound()
    play_startup_sound() # Play startup sound after initialization

    frame = FileManager()
    frame.Show()
    app.MainLoop()

if __name__ == "__main__":
    main()
