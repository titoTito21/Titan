# -*- coding: utf-8 -*-
"""NVDA's `api`: the focus, the foreground, the navigator and the
clipboard - Titan Access's own, seen as NVDA objects (`nvda_shape`)."""

_navigator = [None]


def _seam():
    from titan_access.portable import readerApi
    return readerApi


def getFocusObject():
    return _seam().focus()


def getForegroundObject():
    return _seam().foreground()


def getNavigatorObject():
    return _navigator[0] or getFocusObject()


def setNavigatorObject(obj, isFocus=False):
    _navigator[0] = obj
    return True


def setFocusObject(obj):
    return _seam().set_focus(obj)


def getDesktopObject():
    class _Desktop(object):
        name = 'Desktop'
        role = None

        @property
        def children(self):
            return _seam().top_windows()

        def objectFromPoint(self, x, y):
            return _seam().object_at(x, y)
    return _Desktop()


def getMouseObject():
    return None


def getStatusBar():
    return None


def getReviewPosition():
    return None


def copyToClip(text, notify=False):
    try:
        import wx
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(str(text)))
            finally:
                wx.TheClipboard.Close()
        if notify:
            from .ui import message
            message(str(text))
        return True
    except Exception:                                # noqa: BLE001
        return False


def getClipData():
    try:
        import wx
        data = wx.TextDataObject()
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.GetData(data)
            finally:
                wx.TheClipboard.Close()
        return data.GetText()
    except Exception:                                # noqa: BLE001
        return ''


def processPendingEvents(processEventQueue=True):
    pass


def isTypingProtected():
    return False


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
