# -*- coding: utf-8 -*-
"""NVDA's `gui`: wx is Titan's, so an add-on's own windows are real."""

import wx                                                       # noqa: F401

from . import guiHelper, message, settingsDialogs              # noqa: F401
from .message import messageBox                                 # noqa: F401


class _SysTrayIcon(object):
    """NVDA's tray menu. Its Tools and Preferences menus are REAL wx menus,
    and every handler an add-on binds to an item is remembered, so Titan
    Access offers those items itself (`nvda_host.menu_items`)."""

    def __init__(self):
        self._menus = {}
        self.bound = {}               # item id -> handler

    def _menu(self, name):
        if name not in self._menus:
            self._menus[name] = wx.Menu()
        return self._menus[name]

    @property
    def toolsMenu(self):
        return self._menu('tools')

    @property
    def preferencesMenu(self):
        return self._menu('preferences')

    @property
    def menu(self):
        return self._menu('main')

    @property
    def helpMenu(self):
        return self._menu('help')

    def Bind(self, event, handler, source=None, id=wx.ID_ANY, id2=wx.ID_ANY):
        item_id = source.GetId() if source is not None and \
            hasattr(source, 'GetId') else id
        self.bound[item_id] = handler

    def Unbind(self, event, source=None, id=wx.ID_ANY, id2=wx.ID_ANY,
               handler=None):
        item_id = source.GetId() if source is not None and \
            hasattr(source, 'GetId') else id
        self.bound.pop(item_id, None)
        return True

    def items(self):
        """``[(menu, label, handler)]`` of everything bound."""
        found = []
        for name, menu in self._menus.items():
            for item in menu.GetMenuItems():
                handler = self.bound.get(item.GetId())
                if handler is not None:
                    found.append((name, item.GetItemLabelText(), handler,
                                  item.GetId()))
        return found


class _MainFrame(object):
    def __init__(self):
        self.sysTrayIcon = _SysTrayIcon()

    def prePopup(self):
        pass

    def postPopup(self):
        pass

    def popupSettingsDialog(self, dialog, *args, **kwargs):
        try:
            found = dialog(None, *args, **kwargs)
            found.Show()
        except Exception:                            # noqa: BLE001
            pass

    def Bind(self, event, handler, source=None, id=wx.ID_ANY, id2=wx.ID_ANY):
        self.sysTrayIcon.Bind(event, handler, source, id, id2)

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return lambda *args, **kwargs: None


mainFrame = _MainFrame()


class _SysTrayMenu(object):
    def __init__(self):
        self.menu = None

    def __getattr__(self, name):
        return None


def runScriptModalDialog(dialog, callback=None):
    def run():
        result = dialog.ShowModal()
        if callback:
            callback(result)
        dialog.Destroy()
    wx.CallAfter(run)


def isInMessageBox():
    return False


from .. import permissive as _permissive  # noqa: E402
_permissive(globals())
