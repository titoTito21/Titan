import wx


class LoadingWindow(wx.Frame):
    """Simple loading window displayed during Titan startup."""

    def __init__(self):
        """Initialize a simple empty window with 'Titan' title."""
        super(LoadingWindow, self).__init__(
            None,
            title="Titan",
            style=wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX)
        )

        # Set window size
        self.SetSize((400, 300))

        # Center on screen
        self.Centre()

        # Create empty panel (just blank window)
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))

        # Show the window
        self.Show()

        # Force update to display immediately
        self.Update()
        wx.YieldIfNeeded()

    def close(self):
        """Close the loading window."""
        try:
            self.Close()
            self.Destroy()
        except:
            pass
