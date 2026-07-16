# -*- coding: utf-8 -*-
"""Browsing history for tWeb: JSON-backed list + dialog."""
import wx
import os
import json
import time
from translation import _

from common import _apply_skin_to_tree, config, get_data_path

HISTORY_PATH = get_data_path('tbrowser_history.json')


def _load():
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _save(items):
    try:
        os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
        with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(_("Nie można zapisać historii: {}").format(e))


class HistoryStore:
    def __init__(self):
        self.items = _load()  # newest first

    def add(self, url, title):
        if not url:
            return
        # An immediately-preceding duplicate is a reload/redirect, not a new visit.
        if self.items and self.items[0].get('url') == url:
            self.items[0]['title'] = title or self.items[0].get('title', '')
            self.items[0]['time'] = time.strftime('%Y-%m-%d %H:%M:%S')
        else:
            self.items.insert(0, {
                'url': url,
                'title': title or url,
                'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            })
        try:
            max_entries = config.getint('history', 'max_entries')
        except Exception:
            max_entries = 500
        del self.items[max_entries:]
        _save(self.items)

    def remove(self, index):
        if 0 <= index < len(self.items):
            del self.items[index]
            _save(self.items)

    def clear(self):
        self.items = []
        _save(self.items)


class HistoryDialog(wx.Dialog):
    def __init__(self, parent, store, on_open):
        super(HistoryDialog, self).__init__(parent, title=_("Historia przeglądania"))
        self.store = store
        self.on_open = on_open

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        info_text = wx.StaticText(panel, label=_("Odwiedzone strony:"))
        vbox.Add(info_text, flag=wx.ALL, border=5)

        self.listbox = wx.ListBox(panel, choices=self._labels(), style=wx.LB_SINGLE)
        vbox.Add(self.listbox, proportion=1, flag=wx.ALL | wx.EXPAND, border=5)
        self.listbox.Bind(wx.EVT_KEY_DOWN, self.onKeyDown)

        clear_btn = wx.Button(panel, label=_("Wyczyść historię"))
        clear_btn.Bind(wx.EVT_BUTTON, self.onClear)
        vbox.Add(clear_btn, flag=wx.ALL, border=5)

        panel.SetSizer(vbox)
        self.SetSize((500, 380))
        self.Centre()
        _apply_skin_to_tree(self)

    def _labels(self):
        return ["{} — {}".format(item.get('title') or item.get('url'), item.get('url'))
                for item in self.store.items]

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

    def onClear(self, event):
        self.store.clear()
        self.listbox.Clear()
