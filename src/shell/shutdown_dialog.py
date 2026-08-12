# -*- coding: utf-8 -*-
"""
The Shut Down dialog, as the shell has it.

ReactOS' Explorer does not draw this one itself: `ExitWindowsDialog`
(`dll/win32/shell32/dialogs/dialogs.cpp`) hands it to msgina's
`ShellShutdownDialog` and acts on what comes back.  The dialog is
`IDD_SHUTDOWN` in `dll/win32/msgina`, and this is the same thing built out of
real wx controls, control for control:

    icon   What do you want the computer to do?
           [ Shut down                                   v ]
           Ends your current session and shuts down the
           system so you can safely shut down the power.
                                          [  OK  ] [ Cancel ]

The wording of every entry and of every description is msgina's own
(`IDS_SHUTDOWN_*`, `IDS_SHUTDOWN_*_DESC`), which is what makes this the
ReactOS dialog rather than a dialog that does the same job.

Sleep and hibernate are offered only where Windows says it would take them,
so the list is the list this machine actually has.  There are no pictures
made of text anywhere in it: the icon is a real icon and every entry is a
sentence.
"""

import getpass

import wx

from src.platform_utils import IS_WINDOWS
from src.shell import win_shell
from src.titan_core.translation import _


# ---------------------------------------------------------------------------
# What the computer can be asked to do
# ---------------------------------------------------------------------------
def shutdown_actions():
    """The entries of the combo box, in msgina's order.

    Each is (id, label, description).  Sleep and hibernate drop out on a
    machine that will not do them, which is what msgina does too - it greys
    its own buttons rather than failing when they are pressed.
    """
    try:
        user = getpass.getuser()
    except Exception:
        user = ''

    actions = [
        ('logoff',
         _("Log off \"{user}\"").format(user=user) if user else _("Log off"),
         _("Ends your current session and allows other users to log on to "
           "the system.")),
        ('shutdown', _("Shut down"),
         _("Ends your current session and shuts down the system so you can "
           "safely shut down the power.")),
        ('restart', _("Restart"),
         _("Ends your current session and reboots the system.")),
    ]

    sleep_allowed, hibernate_allowed = win_shell.power_states_allowed()
    if sleep_allowed:
        actions.append(('sleep', _("Sleep"),
                        _("Puts the system in sleep mode.")))
    if hibernate_allowed:
        actions.append(('hibernate', _("Hibernate"),
                        _("Saves the current session and shuts down the "
                          "computer.")))
    # Titan's own entry.  With the system interface replaced this dialog is
    # the only "off" the user has, and leaving Titan is one of the things
    # they may mean by it - the machine keeps running and Windows' own
    # desktop and taskbar come back.
    actions.append(('exit_titan', _("Turn off TCE"),
                    _("Closes Titan and gives the desktop and the taskbar "
                      "back to Windows. The computer stays on.")))
    return actions


def exit_titan():
    """Close Titan itself, as its own window's close button does.

    The shell is taken down on the way out by Titan's normal shutdown (the
    system hooks stop the shell, which unregisters the appbar and puts
    Explorer's taskbar back), so this is the ordinary exit and not a
    separate teardown that could get out of step with it.
    """
    app = wx.GetApp()
    if app is None:
        return False
    frame = app.GetTopWindow()
    if frame is not None and hasattr(frame, 'shutdown_app'):
        wx.CallAfter(frame.shutdown_app)
        return True
    wx.CallAfter(app.ExitMainLoop)
    return True


def perform_shutdown_action(action):
    """Do what was chosen.  True if the machine took it."""
    if action == 'exit_titan':
        return exit_titan()
    if action in ('sleep', 'hibernate'):
        return win_shell.suspend(hibernate=(action == 'hibernate'))
    if action in ('logoff', 'shutdown', 'restart'):
        return win_shell.exit_windows(action)
    return False


# ---------------------------------------------------------------------------
# The dialog
# ---------------------------------------------------------------------------
class ShutdownDialog(wx.Dialog):
    """`IDD_SHUTDOWN`, control for control."""

    def __init__(self, parent=None, default='shutdown'):
        super().__init__(parent, title=_("Shut Down Windows"),
                         style=wx.DEFAULT_DIALOG_STYLE)

        self.actions = shutdown_actions()

        outer = wx.BoxSizer(wx.VERTICAL)
        body = wx.BoxSizer(wx.HORIZONTAL)

        bitmap = self._dialog_icon()
        if bitmap is not None and bitmap.IsOk():
            body.Add(wx.StaticBitmap(self, bitmap=bitmap),
                     flag=wx.ALIGN_TOP | wx.RIGHT, border=12)

        column = wx.BoxSizer(wx.VERTICAL)
        prompt = wx.StaticText(
            self, label=_("&What do you want the computer to do?"))
        column.Add(prompt, flag=wx.BOTTOM, border=6)

        self.combo = wx.ComboBox(
            self, choices=[label for _id, label, _desc in self.actions],
            size=(280, -1), style=wx.CB_READONLY)
        self.combo.SetName(_("What do you want the computer to do?"))
        column.Add(self.combo, flag=wx.EXPAND | wx.BOTTOM, border=8)

        # The line that says what the chosen entry will actually do.  It is
        # part of the dialog and not a tooltip, so a screen reader reaches it
        # by moving through the window like anything else.
        self.description = wx.StaticText(self, label='', size=(280, 40))
        self.description.SetName(_("Description"))
        column.Add(self.description, 1, flag=wx.EXPAND)

        body.Add(column, 1, flag=wx.EXPAND)
        outer.Add(body, 1, flag=wx.ALL | wx.EXPAND, border=12)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.AddStretchSpacer()
        self.ok_button = wx.Button(self, wx.ID_OK, _("OK"))
        self.cancel_button = wx.Button(self, wx.ID_CANCEL, _("Cancel"))
        buttons.Add(self.ok_button, flag=wx.LEFT, border=6)
        buttons.Add(self.cancel_button, flag=wx.LEFT, border=6)
        outer.Add(buttons, flag=wx.ALL | wx.EXPAND, border=12)

        self.SetSizerAndFit(outer)
        self.CentreOnScreen()

        self.combo.Bind(wx.EVT_COMBOBOX, self._on_choice)
        self.ok_button.SetDefault()

        index = self._index_of(default)
        self.combo.SetSelection(index)
        self._update_description()
        self.combo.SetFocus()

        self.action = None

    def _index_of(self, action_id):
        for index, (identifier, _label, _desc) in enumerate(self.actions):
            if identifier == action_id:
                return index
        return 0

    @staticmethod
    def _dialog_icon():
        """A real icon; never a character standing in for one."""
        if IS_WINDOWS:
            try:
                # 27 is shell32's shut-down icon.
                handle = win_shell.shell_icon_handle(27, 32)
                if handle:
                    icon = wx.Icon()
                    icon.SetHandle(handle)
                    icon.SetWidth(32)
                    icon.SetHeight(32)
                    bitmap = wx.Bitmap()
                    bitmap.CopyFromIcon(icon)
                    if bitmap.IsOk():
                        return bitmap
            except Exception:
                pass
        return wx.ArtProvider.GetBitmap(wx.ART_QUIT, wx.ART_OTHER, (32, 32))

    def _on_choice(self, _event):
        self._update_description()

    def _update_description(self):
        index = self.combo.GetSelection()
        if 0 <= index < len(self.actions):
            self.description.SetLabel(self.actions[index][2])
            self.description.Wrap(280)
            self.Layout()

    def selected_action(self):
        index = self.combo.GetSelection()
        if 0 <= index < len(self.actions):
            return self.actions[index][0]
        return None


def show_shutdown_dialog(parent=None, default='shutdown'):
    """Put the Shut Down dialog up and do what it says.

    Returns the id of what was done, or None when the user cancelled or the
    machine refused.
    """
    dialog = ShutdownDialog(parent, default)
    try:
        if dialog.ShowModal() != wx.ID_OK:
            return None
        action = dialog.selected_action()
    finally:
        dialog.Destroy()

    if not action:
        return None
    if perform_shutdown_action(action):
        return action
    # The same sentence the shell's own actions use when Windows says no,
    # so there is one wording for it and one translation of it.
    wx.MessageBox(_("Windows refused that."), _("Shut Down Windows"),
                  wx.OK | wx.ICON_ERROR, parent)
    return None


# ---------------------------------------------------------------------------
# Alt+F4, everywhere in the shell
# ---------------------------------------------------------------------------
_dialog_open = False


def shell_alt_f4(window=None):
    """Alt+F4 in any shell window: the Shut Down dialog.

    Windows answers Alt+F4 with this dialog whenever the shell itself has
    the keyboard, and every window Titan's shell puts up is furniture rather
    than a document: the taskbar, the desktop and the Start menu have
    nothing to close.  Letting wx take Alt+F4 there destroyed a frame the
    shell still holds - the bar disappeared and the next thing that touched
    it crashed - so the whole shell answers the key the way the desktop
    already did.

    Returns True when the key was handled, whatever the user then chose.
    """
    global _dialog_open
    if _dialog_open:
        # A second Alt+F4 while the dialog is up is the dialog's own key.
        return True
    _dialog_open = True
    try:
        show_shutdown_dialog(window)
    except Exception as error:
        print(f"[TitanShell] could not open the shutdown dialog: {error}")
        return False
    finally:
        _dialog_open = False
    return True


def is_shutdown_dialog_open():
    """True while the Shut Down dialog is up (it is modal and one at a time)."""
    return _dialog_open
