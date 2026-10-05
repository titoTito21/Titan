# -*- coding: utf-8 -*-
"""NVDA's `ui`: a message is said by the reader (and brailled)."""


def message(text, speechPriority=None, brailleText=None):
    from .speech import _reader_say
    _reader_say(text)
    try:
        from titan_access.engine import get_engine
        engine = get_engine()
        braille = getattr(engine, 'braille', None)
        if braille is not None and hasattr(braille, 'message'):
            braille.message(str(brailleText or text))
    except Exception:                                # noqa: BLE001
        pass


def reviewMessage(text, speechPriority=None):
    message(text)


def browseableMessage(message_, title=None, isHtml=False, closeButton=False,
                      copyButton=False, sanitizeHtmlFunc=None):
    """Shown in a read-only window, as NVDA shows it in a browseable one."""
    text = str(message_ or '')
    if isHtml:
        import re
        text = re.sub(r'<[^>]+>', '', text)
    try:
        import wx

        def show():
            dialog = wx.Dialog(None, title=str(title or ''),
                               style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
            box = wx.TextCtrl(dialog, value=text, size=(560, 380),
                              style=wx.TE_MULTILINE | wx.TE_READONLY)
            sizer = wx.BoxSizer(wx.VERTICAL)
            sizer.Add(box, 1, wx.EXPAND | wx.ALL, 6)
            sizer.Add(dialog.CreateButtonSizer(wx.CLOSE), 0, wx.ALL, 6)
            dialog.SetSizerAndFit(sizer)
            dialog.SetEscapeId(wx.ID_CLOSE)
            box.SetFocus()
            dialog.ShowModal()
            dialog.Destroy()
        wx.CallAfter(show)
    except Exception:                                # noqa: BLE001
        message(text)


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
