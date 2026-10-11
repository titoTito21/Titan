# -*- coding: utf-8 -*-
"""The warning a threat is put in front of the user with.

**Why not `wx.MessageDialog`.** On Windows wx builds a message dialog with
buttons of its own wording as a TaskDialog, and a TaskDialog DRAWS its icon:
there is no icon control in it, only a UI Automation image with no window of
its own. Both of Titan's readers decide that a dialog is a warning by the
icon the dialog holds (`dialog_kind`, Titan Access' `_dialog_icon_kind`) -
which is the only honest way an application in a process of its own can say
it - and on a TaskDialog they find nothing, so "threat found" would be read
as a dialog like any other.

A classic message box (`MessageBoxW` with ``MB_ICONWARNING``) holds the real
warning icon in a static control, and both readers say "warning" before a
word of it. Its buttons are given the antivirus' own words through a CBT
hook on this thread - the standard way to relabel a message box: the hook
sees the box being activated and renames its buttons before it is shown,
and is removed at once.

Elsewhere (Linux, GTK) `wx.MessageDialog` is a GtkMessageDialog, which ATK
reports as an ALERT with the warning type - already what a reader needs.
"""

import ctypes
import sys

import wx

IS_WINDOWS = sys.platform == 'win32'

MB_YESNO = 0x4
MB_YESNOCANCEL = 0x3
MB_ICONWARNING = 0x30
MB_DEFBUTTON1 = 0x0
MB_TASKMODAL = 0x2000
IDYES, IDNO, IDCANCEL = 6, 7, 2
WH_CBT = 5
HCBT_ACTIVATE = 5


def _message_box(parent, message, title, labels):
    """MessageBoxW with ``labels`` on its buttons (two or three); answers
    'yes', 'no' or 'cancel'."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hook_proc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                   ctypes.c_size_t, ctypes.c_ssize_t)
    user32.CallNextHookEx.argtypes = (ctypes.c_void_p, ctypes.c_int,
                                      ctypes.c_size_t, ctypes.c_ssize_t)
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.SetWindowsHookExW.argtypes = (ctypes.c_int, hook_proc,
                                         ctypes.c_void_p, ctypes.c_ulong)
    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    user32.UnhookWindowsHookEx.argtypes = (ctypes.c_void_p,)
    user32.SetDlgItemTextW.argtypes = (ctypes.c_void_p, ctypes.c_int,
                                       ctypes.c_wchar_p)
    user32.MessageBoxW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p,
                                   ctypes.c_wchar_p, ctypes.c_uint)
    ids = (IDYES, IDNO, IDCANCEL)
    state = {'hook': None}

    def on_cbt(code, wparam, lparam):
        if code == HCBT_ACTIVATE and state['hook']:
            for control, label in zip(ids, labels):
                user32.SetDlgItemTextW(ctypes.c_void_p(wparam), control, label)
            user32.UnhookWindowsHookEx(state['hook'])
            state['hook'] = None
            return 0
        return user32.CallNextHookEx(None, code, wparam, lparam)

    # Held for as long as the hook exists: Windows keeps the ADDRESS.
    callback = hook_proc(on_cbt)
    state['hook'] = user32.SetWindowsHookExW(WH_CBT, callback, None,
                                             kernel32.GetCurrentThreadId())
    style = MB_ICONWARNING | MB_DEFBUTTON1 | (
        MB_YESNOCANCEL if len(labels) == 3 else MB_YESNO)
    owner = None
    if parent is not None:
        try:
            owner = ctypes.c_void_p(int(parent.GetHandle()))
        except Exception:                            # noqa: BLE001
            owner = None
    if owner is None:
        style |= MB_TASKMODAL
    try:
        answer = user32.MessageBoxW(owner, message, title, style)
    finally:
        if state['hook']:
            user32.UnhookWindowsHookEx(state['hook'])
            state['hook'] = None
    del callback
    return {IDYES: 'yes', IDNO: 'no'}.get(answer, 'cancel')


def warning(parent, message, title, labels):
    """A warning with two or three buttons worded ``labels``; answers
    'yes' (the first), 'no' (the second) or 'cancel' (the third, Escape,
    or the box closed)."""
    if IS_WINDOWS:
        try:
            return _message_box(parent, message, title, labels)
        except Exception as error:                   # noqa: BLE001
            print(f'[TitanAntivirus] message box: {error}')
    style = wx.ICON_WARNING | (wx.YES_NO | wx.CANCEL if len(labels) == 3
                               else wx.YES_NO)
    dialog = wx.MessageDialog(parent, message, title, style)
    if len(labels) == 3:
        dialog.SetYesNoCancelLabels(*labels)
    else:
        dialog.SetYesNoLabels(*labels)
    answer = dialog.ShowModal()
    dialog.Destroy()
    return {wx.ID_YES: 'yes', wx.ID_NO: 'no'}.get(answer, 'cancel')
