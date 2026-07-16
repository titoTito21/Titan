# -*- coding: utf-8 -*-
"""Find-in-page bar for tWeb.

Docks above the status bar. Delegates the actual search to the active
BrowserTab, which implements the small "find target" contract:

    tab.find_text(text, match_case, whole_word, backwards) -> bool (found)
    tab.clear_find_highlight()
    tab.focus_content()

A WebView tab answers this via the native wx.html2.WebView.Find(); a
virtual-buffer tab answers it with a manual string search over the TextCtrl.
"""
import wx
from translation import _


class FindBar(wx.Panel):
    def __init__(self, parent, get_active_tab):
        super(FindBar, self).__init__(parent)
        self.get_active_tab = get_active_tab

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.text = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.match_case_cb = wx.CheckBox(self, label=_("Uwzględnij wielkość liter"))
        self.whole_word_cb = wx.CheckBox(self, label=_("Całe słowo"))
        prev_btn = wx.Button(self, label=_("Poprzedni"))
        next_btn = wx.Button(self, label=_("Następny"))
        close_btn = wx.Button(self, label=_("Zamknij"))

        sizer.Add(wx.StaticText(self, label=_("Znajdź:")), flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL, border=5)
        sizer.Add(self.text, proportion=1, flag=wx.ALL | wx.EXPAND, border=5)
        sizer.Add(self.match_case_cb, flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL, border=5)
        sizer.Add(self.whole_word_cb, flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL, border=5)
        sizer.Add(prev_btn, flag=wx.ALL, border=5)
        sizer.Add(next_btn, flag=wx.ALL, border=5)
        sizer.Add(close_btn, flag=wx.ALL, border=5)
        self.SetSizer(sizer)

        self.text.Bind(wx.EVT_TEXT_ENTER, lambda e: self.find_next())
        self.text.Bind(wx.EVT_TEXT, lambda e: self.find_next(from_typing=True))
        self.text.Bind(wx.EVT_KEY_DOWN, self.onTextKeyDown)
        prev_btn.Bind(wx.EVT_BUTTON, lambda e: self.find_previous())
        next_btn.Bind(wx.EVT_BUTTON, lambda e: self.find_next())
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.CloseBar())

        self.Hide()

    def OpenBar(self):
        self.Show()
        self.GetParent().Layout()
        self.text.SetFocus()
        self.text.SelectAll()

    def CloseBar(self):
        tab = self.get_active_tab()
        if tab is not None:
            try:
                tab.clear_find_highlight()
            except Exception:
                pass
        self.Hide()
        self.GetParent().Layout()
        if tab is not None:
            try:
                tab.focus_content()
            except Exception:
                pass

    def onTextKeyDown(self, event):
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_ESCAPE:
            self.CloseBar()
        elif keycode == wx.WXK_RETURN and event.ShiftDown():
            self.find_previous()
        else:
            event.Skip()

    def find_next(self, from_typing=False, backwards=False):
        tab = self.get_active_tab()
        term = self.text.GetValue()
        if tab is None or not term:
            return
        found = tab.find_text(
            term,
            match_case=self.match_case_cb.GetValue(),
            whole_word=self.whole_word_cb.GetValue(),
            backwards=backwards,
        )
        if not from_typing and not found:
            wx.Bell()

    def find_previous(self):
        self.find_next(backwards=True)
