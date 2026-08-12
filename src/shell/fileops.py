# -*- coding: utf-8 -*-
"""
Cut, copy and paste of files, as the shell does them.

One module because two windows do it - the desktop and the shell's Explorer -
and because the part that is easy to get wrong has to be got right in exactly
one place: a file on the clipboard is a `CF_HDROP` list, and whether it was
**cut** or **copied** is a second format Windows calls "Preferred
DropEffect".  Without that format a cut quietly behaves as a copy, which is
the kind of wrong that loses the user's intent silently.

Everything here works on a list of paths, so a selection of one and a
selection of forty go the same way.
"""

import os

import wx

# `DROPEFFECT_MOVE` and `DROPEFFECT_COPY`, as ole2.h has them.
DROPEFFECT_MOVE = 2
DROPEFFECT_COPY = 5


def copy_to_clipboard(paths, cut=False):
    """Put files on the clipboard, saying whether they were cut or copied."""
    paths = [str(path) for path in paths if path]
    if not paths:
        return False
    try:
        files = wx.FileDataObject()
        for path in paths:
            files.AddFile(path)
        data = wx.DataObjectComposite()
        data.Add(files, True)
        effect = wx.CustomDataObject(wx.DataFormat('Preferred DropEffect'))
        effect.SetData((DROPEFFECT_MOVE if cut
                        else DROPEFFECT_COPY).to_bytes(4, 'little'))
        data.Add(effect)
        if not wx.TheClipboard.Open():
            return False
        try:
            wx.TheClipboard.SetData(data)
            wx.TheClipboard.Flush()
        finally:
            wx.TheClipboard.Close()
        return True
    except Exception as error:
        print(f"[TitanShell] could not copy to the clipboard: {error}")
        return False


def clipboard_files(cut_paths=()):
    """What is on the clipboard, and whether it was cut.

    `cut_paths` is what this window itself cut last, which is the fallback
    for the case where the drop-effect format did not survive - some
    programs put files on the clipboard without it.
    """
    paths, move = [], False
    try:
        if not wx.TheClipboard.Open():
            return paths, move
        try:
            files = wx.FileDataObject()
            if wx.TheClipboard.GetData(files):
                paths = list(files.GetFilenames())
            effect = wx.CustomDataObject(
                wx.DataFormat('Preferred DropEffect'))
            if wx.TheClipboard.GetData(effect):
                raw = effect.GetData()
                if raw:
                    move = (int.from_bytes(bytes(raw)[:4], 'little')
                            & DROPEFFECT_MOVE) == DROPEFFECT_MOVE
        finally:
            wx.TheClipboard.Close()
    except Exception as error:
        print(f"[TitanShell] could not read the clipboard: {error}")
    if not move and cut_paths:
        cut = [os.path.normcase(str(path)) for path in cut_paths]
        move = any(os.path.normcase(path) in cut for path in paths)
    return paths, move
