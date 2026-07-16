# -*- coding: utf-8 -*-
"""Bookmarks for tWeb: JSON-backed list + dialog."""
import wx
import os
import json
from translation import _

from common import _apply_skin_to_tree, get_data_path

BOOKMARKS_PATH = get_data_path('tbrowser_bookmarks.json')


def _load():
    if not os.path.exists(BOOKMARKS_PATH):
        return []
    try:
        with open(BOOKMARKS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _save(items):
    try:
        os.makedirs(os.path.dirname(BOOKMARKS_PATH), exist_ok=True)
        with open(BOOKMARKS_PATH, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(_("Nie można zapisać zakładek: {}").format(e))


class BookmarkStore:
    def __init__(self):
        self.items = _load()

    def is_bookmarked(self, url):
        return any(b.get('url') == url for b in self.items)

    def toggle(self, url, title):
        """Add or remove *url*. Returns True if it is now bookmarked."""
        for i, b in enumerate(self.items):
            if b.get('url') == url:
                del self.items[i]
                _save(self.items)
                return False
        self.items.insert(0, {'url': url, 'title': title or url})
        _save(self.items)
        return True

    def remove(self, index):
        if 0 <= index < len(self.items):
            del self.items[index]
            _save(self.items)


class BookmarksDialog(wx.Dialog):
    def __init__(self, parent, store, on_open):
        super(BookmarksDialog, self).__init__(parent, title=_("Zakładki"))
        self.store = store
        self.on_open = on_open

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        info_text = wx.StaticText(panel, label=_("Zapisane zakładki:"))
        vbox.Add(info_text, flag=wx.ALL, border=5)

        self.listbox = wx.ListBox(panel, choices=self._labels(), style=wx.LB_SINGLE)
        vbox.Add(self.listbox, proportion=1, flag=wx.ALL | wx.EXPAND, border=5)
        self.listbox.Bind(wx.EVT_KEY_DOWN, self.onKeyDown)

        panel.SetSizer(vbox)
        self.SetSize((450, 320))
        self.Centre()
        _apply_skin_to_tree(self)

    def _labels(self):
        return ["{} — {}".format(b.get('title') or b.get('url'), b.get('url'))
                for b in self.store.items]

    def onKeyDown(self, event):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_RETURN:
            self.openSelected()
        elif keycode == wx.WXK_DELETE:
            self.removeSelected()
        else:
            event.Skip()

    def openSelected(self):
        selection = self.listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        item = self.store.items[selection]
        self.on_open(item['url'])
        self.Close()

    def removeSelected(self):
        selection = self.listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        self.store.remove(selection)
        self.listbox.Delete(selection)
