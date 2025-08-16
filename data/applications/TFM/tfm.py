# TFM/tfm.py
import wx
import os
import sys
from translation import _


# Now, import the rest of the application modules
from gui import FileManager
from sound import initialize_sound, play_startup_sound # Import initialize_sound and play_startup_sound

def main(initial_path=None):
    app = wx.App(False)
    # Initialize sound after wx.App is created, especially if using wx.StandardPaths
    initialize_sound()
    play_startup_sound() # Play startup sound after initialization

    frame = FileManager(initial_path=initial_path)
    frame.Show()
    app.MainLoop()

if __name__ == "__main__":
    # Check for command line arguments
    initial_path = None
    if len(sys.argv) > 1:
        initial_path = sys.argv[1]
        # Validate path exists
        if not os.path.exists(initial_path):
            print(f"Warning: Path {initial_path} does not exist, using default")
            initial_path = None
    
    main(initial_path)
