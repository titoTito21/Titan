# -*- coding: utf-8 -*-
"""
The Run dialog, as the shell has it.

Until now "Run..." handed the job to Windows (`rundll32 shell32.dll,#61`),
which is the one thing a shell replacement must not do: the window that comes
up belongs to Explorer, it is not skinned like the rest of Titan, Titan cannot
say anything about it, and on a machine where Explorer's shell is being
replaced it is the wrong window entirely.

This is ReactOS' `RunFileDlg` (`dll/win32/shell32/dialogs/dialogs.cpp`,
`IDD_RUN`) rebuilt out of real wx controls, control for control:

    icon   Type the name of a program, folder, document, or Internet
           resource, and Windows will open it for you.
    Open:  [ combo box with the history                            v ]
                                    [  OK  ] [ Cancel ] [ Browse... ]

The history is the *real* one - `HKCU\\Software\\Microsoft\\Windows\\
CurrentVersion\\Explorer\\RunMRU`, the same list Explorer keeps - so what the
user typed into Windows' Run box yesterday is in Titan's today and the other
way round.  Where the registry cannot be read it falls back to a file of its
own, so the dialog still remembers on a machine that is locked down.

No emoji anywhere: the icon is the real shell icon for the dialog, and every
button says what it does in words.
"""

import json
import os

import wx

from src.platform_utils import IS_WINDOWS, get_user_data_dir
from src.titan_core.translation import _

if IS_WINDOWS:
    import winreg

RUN_MRU_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\RunMRU"
MRU_LIMIT = 26


# ---------------------------------------------------------------------------
# The history
# ---------------------------------------------------------------------------
def _mru_file():
    try:
        return os.path.join(get_user_data_dir(), 'shell_run_mru.json')
    except Exception:
        return None


def _read_registry_mru():
    """Explorer's own RunMRU, in the order it puts it in.

    The key holds one value per entry named with a letter (`a`, `b`, `c`...)
    and a `MRUList` value giving the order, which is the order the combo box
    has to be in - the letters themselves mean nothing.  Each entry ends with
    `\\1`, which is Explorer's terminator and not part of what was typed.
    """
    if not IS_WINDOWS:
        return []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_MRU_KEY) as key:
            try:
                order = winreg.QueryValueEx(key, 'MRUList')[0] or ''
            except OSError:
                order = ''
            entries = []
            for letter in order:
                try:
                    value = winreg.QueryValueEx(key, letter)[0] or ''
                except OSError:
                    continue
                value = value.split('\\1')[0].strip()
                if value and value not in entries:
                    entries.append(value)
            return entries
    except OSError:
        return []
    except Exception as error:
        print(f"[TitanShell] could not read the Run history: {error}")
        return []


def _write_registry_mru(entries):
    if not IS_WINDOWS:
        return False
    letters = 'abcdefghijklmnopqrstuvwxyz'
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_MRU_KEY) as key:
            order = ''
            for letter, value in zip(letters, entries[:MRU_LIMIT]):
                winreg.SetValueEx(key, letter, 0, winreg.REG_SZ,
                                  value + '\\1')
                order += letter
            winreg.SetValueEx(key, 'MRUList', 0, winreg.REG_SZ, order)
        return True
    except Exception as error:
        print(f"[TitanShell] could not save the Run history: {error}")
        return False


def _read_file_mru():
    path = _mru_file()
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            entries = json.load(handle)
        return [str(entry) for entry in entries if str(entry).strip()]
    except Exception:
        return []


def _write_file_mru(entries):
    path = _mru_file()
    if not path:
        return
    try:
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(entries[:MRU_LIMIT], handle, indent=2)
    except Exception as error:
        print(f"[TitanShell] could not save the Run history: {error}")


def run_history():
    """What the user has run before, most recent first."""
    entries = _read_registry_mru()
    for entry in _read_file_mru():
        if entry not in entries:
            entries.append(entry)
    return entries[:MRU_LIMIT]


def remember_command(command):
    """Put a command at the top of the history, keeping it unique."""
    command = (command or '').strip()
    if not command:
        return
    entries = [entry for entry in run_history() if entry != command]
    entries.insert(0, command)
    if not _write_registry_mru(entries):
        _write_file_mru(entries)


# ---------------------------------------------------------------------------
# Running what was typed
# ---------------------------------------------------------------------------
def run_command(command, parent=None, remember=True):
    """Do what the Open box says, and say so when it cannot be done.

    Environment variables are expanded first (`%temp%` is a thing people
    type into this box), and the command goes through the shell's own
    "open" verb rather than through a subprocess, so a folder, a document,
    a web address and a program all work - which is what the dialog's own
    text promises.
    """
    command = (command or '').strip()
    if not command:
        return False

    expanded = os.path.expandvars(command)
    try:
        from src.shell import win_shell
        opened = win_shell.shell_execute(expanded)
    except Exception as error:
        print(f"[TitanShell] Run failed: {error}")
        opened = False

    if not opened:
        wx.MessageBox(
            _("Windows cannot find '{command}'. Make sure you typed the "
              "name correctly, and then try again.").format(command=command),
            _("Run"), wx.OK | wx.ICON_ERROR, parent)
        return False

    if remember:
        remember_command(command)
    return True


# ---------------------------------------------------------------------------
# The dialog
# ---------------------------------------------------------------------------
class RunDialog(wx.Dialog):
    """`IDD_RUN`, control for control."""

    def __init__(self, parent=None, command=''):
        super().__init__(parent, title=_("Run"),
                         style=wx.DEFAULT_DIALOG_STYLE)

        outer = wx.BoxSizer(wx.VERTICAL)

        # The icon and the paragraph that explains what the box is for.
        top = wx.BoxSizer(wx.HORIZONTAL)
        bitmap = self._dialog_icon()
        if bitmap is not None and bitmap.IsOk():
            icon = wx.StaticBitmap(self, bitmap=bitmap)
            top.Add(icon, flag=wx.ALIGN_TOP | wx.RIGHT, border=12)
        prompt = wx.StaticText(
            self,
            label=_("Type the name of a program, folder, document, or "
                    "Internet resource, and Windows will open it for you."))
        prompt.Wrap(320)
        top.Add(prompt, 1, flag=wx.ALIGN_CENTER_VERTICAL)
        outer.Add(top, flag=wx.ALL | wx.EXPAND, border=12)

        # Open: [combo]
        row = wx.BoxSizer(wx.HORIZONTAL)
        label = wx.StaticText(self, label=_("&Open:"))
        row.Add(label, flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=8)
        # A fixed width, because the history holds whatever was typed into
        # it and one long web address would otherwise make the dialog as
        # wide as the screen.
        self.combo = wx.ComboBox(self, value=command,
                                 choices=run_history(),
                                 size=(300, -1),
                                 style=wx.CB_DROPDOWN)
        self.combo.SetName(_("Open"))
        row.Add(self.combo, 1, flag=wx.ALIGN_CENTER_VERTICAL)
        outer.Add(row, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND,
                  border=12)

        # OK / Cancel / Browse...
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.AddStretchSpacer()
        self.ok_button = wx.Button(self, wx.ID_OK, _("OK"))
        self.cancel_button = wx.Button(self, wx.ID_CANCEL, _("Cancel"))
        self.browse_button = wx.Button(self, wx.ID_ANY, _("&Browse..."))
        for button in (self.ok_button, self.cancel_button,
                       self.browse_button):
            buttons.Add(button, flag=wx.LEFT, border=6)
        outer.Add(buttons, flag=wx.ALL | wx.EXPAND, border=12)

        self.SetSizerAndFit(outer)
        self.CentreOnScreen()

        self.browse_button.Bind(wx.EVT_BUTTON, self._on_browse)
        self.ok_button.Bind(wx.EVT_BUTTON, self._on_ok)
        self.combo.Bind(wx.EVT_TEXT_ENTER, self._on_ok)
        self.ok_button.SetDefault()
        self.combo.SetFocus()
        self.combo.SetInsertionPointEnd()

        self.command = ''

    @staticmethod
    def _dialog_icon():
        """The shell's own Run icon, and a drawn one where there is none.

        A real icon and never a character standing in for one - a picture
        made of text is read out as text by every screen reader on the
        machine, and it is not what the dialog looks like anyway.
        """
        if IS_WINDOWS:
            try:
                from src.shell import win_shell
                # 24 is the icon shell32 gives the Run dialog.
                handle = win_shell.shell_icon_handle(24, 32)
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
        return wx.ArtProvider.GetBitmap(wx.ART_EXECUTABLE_FILE, wx.ART_OTHER,
                                        (32, 32))

    def _on_browse(self, _event):
        """Browse... puts the file that was picked into the Open box."""
        wildcard = _("Programs") + " (*.exe;*.bat;*.cmd;*.com)|" \
            "*.exe;*.bat;*.cmd;*.com|" + _("All files") + " (*.*)|*.*"
        dialog = wx.FileDialog(self, _("Browse"), wildcard=wildcard,
                               style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        try:
            if dialog.ShowModal() == wx.ID_OK:
                path = dialog.GetPath()
                # A path with a space in it has to be quoted, or everything
                # after the space is read as an argument.
                self.combo.SetValue(f'"{path}"' if ' ' in path else path)
                self.combo.SetFocus()
                self.combo.SetInsertionPointEnd()
        finally:
            dialog.Destroy()

    def _on_ok(self, _event):
        self.command = self.combo.GetValue().strip()
        if not self.command:
            self.combo.SetFocus()
            return
        self.EndModal(wx.ID_OK)


def show_run_dialog(parent=None, command=''):
    """Put the Run dialog up and do what it says.  True if something ran."""
    dialog = RunDialog(parent, command)
    try:
        if dialog.ShowModal() != wx.ID_OK:
            return False
        return run_command(dialog.command, parent)
    finally:
        dialog.Destroy()
