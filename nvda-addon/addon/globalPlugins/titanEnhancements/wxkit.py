# -*- coding: utf-8 -*-
"""The little of NVDA's GUI kit the manager windows use, for either reader.

`managerGui` and `classManager` are real wx dialogs - a notebook, lists,
drop-downs, buttons - and they were built with NVDA's ``gui.guiHelper``:
a sizer helper that adds a control with a label in front of it, a button
row, and ``gui.mainFrame`` to hang the dialog on. That is the ONLY reason
those two windows could not be shared with Titan Access, which has wx and
a frame of its own but no ``gui`` module. This answers the same four
things - the sizer helper, the button helper, the frame, a message box -
out of NVDA where it is, and out of plain wx everywhere else, so the two
windows are one file in both readers.
"""


def helper():
    """NVDA's ``guiHelper``, or an equivalent made of plain wx."""
    try:
        from gui import guiHelper
        return guiHelper
    except Exception:                                # noqa: BLE001
        return _PlainHelpers


def frame():
    """The window a dialog belongs to: NVDA's, or the reader's own."""
    try:
        import gui
        found = getattr(gui, 'mainFrame', None)
        if found is not None:
            return found
    except Exception:                                # noqa: BLE001
        pass
    try:
        from . import compat
        found = getattr(getattr(compat, 'gui', None), 'mainFrame', None)
        if found is not None:
            return found
    except Exception:                                # noqa: BLE001
        pass
    try:
        import wx
        return wx.GetApp().GetTopWindow() if wx.GetApp() else None
    except Exception:                                # noqa: BLE001
        return None


def message_box(text, caption, style=None):
    """A message box, through NVDA's where there is one."""
    import wx
    if style is None:
        style = wx.OK | wx.ICON_INFORMATION
    try:
        import gui
        return gui.messageBox(text, caption, style)
    except Exception:                                # noqa: BLE001
        pass
    return wx.MessageBox(text, caption, style, frame())


class _PlainHelpers:
    """``BoxSizerHelper`` and ``ButtonHelper`` as NVDA spells them."""

    class BoxSizerHelper:
        def __init__(self, parent, orientation=None, sizer=None):
            import wx
            self.parent = parent
            self.sizer = sizer if sizer is not None else wx.BoxSizer(
                orientation if orientation is not None else wx.VERTICAL)
            self._orientation = self.sizer.GetOrientation()

        def addItem(self, item, **kwargs):
            import wx
            if isinstance(item, _PlainHelpers.BoxSizerHelper) \
                    or isinstance(item, _PlainHelpers.ButtonHelper):
                self.sizer.Add(item.sizer, flag=wx.ALL | wx.EXPAND, border=5)
                return item
            flag = kwargs.pop('flag', wx.ALL | wx.EXPAND)
            border = kwargs.pop('border', 5)
            proportion = kwargs.pop('proportion', 0)
            self.sizer.Add(item, proportion, flag, border)
            return item

        def addLabeledControl(self, label, control_class, **kwargs):
            import wx
            row = wx.BoxSizer(wx.HORIZONTAL if self._orientation == wx.VERTICAL
                              else wx.VERTICAL)
            text = wx.StaticText(self.parent, label=label)
            control = control_class(self.parent, **kwargs)
            try:
                control.SetName(label.replace('&', ''))
            except Exception:                        # noqa: BLE001
                pass
            row.Add(text, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            row.Add(control, 1, wx.EXPAND)
            self.sizer.Add(row, 0, wx.EXPAND | wx.ALL, 5)
            return control

        def addDialogDismissButtons(self, buttons):
            import wx
            sizer = getattr(buttons, 'sizer', buttons)
            self.sizer.Add(sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
            return buttons

    class ButtonHelper:
        def __init__(self, orientation=None):
            import wx
            self.sizer = wx.BoxSizer(
                orientation if orientation is not None else wx.HORIZONTAL)

        def addButton(self, parent, label='', id=None, **kwargs):
            import wx
            button = wx.Button(parent, id if id is not None else wx.ID_ANY,
                               label=label, **kwargs)
            self.sizer.Add(button, 0, wx.ALL, 4)
            return button
