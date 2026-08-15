# -*- coding: utf-8 -*-
"""
A Start menu somebody else wrote - the whole point of `provides = start_menu`.

Titan ships two Start menus (the XP one and the classic one).  This is a
third, from an add-on, and it is chosen exactly where the other two are:
**taskbar and Start menu properties -> Start menu**, where every installed
add-on that provides one appears as a radio button beside them.

What it has to be is a window with `Show`, `Hide` and `IsShown`; everything
else - where it appears, what is on it, how it is navigated - is the
add-on's own business.  This one is deliberately the simplest thing that is
still a real Start menu: one search box and one list, no columns, no
branches, so it is a demonstration that can be read in one sitting AND a
menu somebody with a screen reader might genuinely prefer.

Everything it does, it does through the Titan Action API (`api.run_action`),
which is what an add-on should reach for before it reaches for Titan's
internals: those are the same calls the AI, a macro and the Action Bus make.
"""

import wx

try:
    from src.titan_core.translation import _
except Exception:                                    # pragma: no cover
    def _(text):
        return text


MENU_WIDTH = 320
MENU_HEIGHT = 420


class SimpleStartMenu(wx.Frame):
    """One search box, one list, the bottom-left corner of the screen."""

    def __init__(self, api, parent=None):
        super().__init__(parent, title=_("Start menu"),
                         style=wx.FRAME_NO_TASKBAR | wx.BORDER_SIMPLE
                         | wx.FRAME_FLOAT_ON_PARENT)
        self.api = api
        self._entries = []

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.search = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.search.SetHint(_("Search"))
        self.list = wx.ListBox(panel, style=wx.LB_SINGLE)
        sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 4)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 4)
        panel.SetSizer(sizer)

        # The name a screen reader reads: a list control has no window text
        # of its own, so wx's `SetName` would never reach one.
        try:
            from src.shell.a11y import name_control
            name_control(self.list, _("Start menu"))
            name_control(self.search, _("Search"))
        except Exception:
            pass

        self.search.Bind(wx.EVT_TEXT, self._filter)
        self.search.Bind(wx.EVT_TEXT_ENTER, self._activate)
        self.list.Bind(wx.EVT_LISTBOX_DCLICK, self._activate)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_ACTIVATE, self._on_activate)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        self.SetSize((MENU_WIDTH, MENU_HEIGHT))

    # -- what is on it --------------------------------------------------
    def _build_entries(self):
        """Everything the menu can start, asked of Titan itself.

        `titan.list_addons` and the app/game managers are the same source
        the built-in menus read, so this menu cannot disagree with them
        about what is installed.
        """
        entries = [
            (_("Titan"), self._show_titan),
            (_("Settings"), lambda: self.api.run_action('titan',
                                                        'open_settings')),
            (_("File manager"), lambda: self.api.run_action('shell',
                                                            'open_explorer')),
            (_("Run..."), self._run_dialog),
        ]
        for name in self._titan_items('applications'):
            entries.append((name, self._starter('app', name)))
        for name in self._titan_items('games'):
            entries.append((name, self._starter('game', name)))
        entries.append((_("Turn Off Computer..."), self._shut_down))
        return entries

    def _show_titan(self):
        shell = self.api.shell()
        if shell is not None:
            shell.show_titan_window()

    def _run_dialog(self):
        from src.shell.run_dialog import show_run_dialog
        show_run_dialog(self.GetParent())

    def _shut_down(self):
        # Titan's own Shut Down dialog rather than a list of the choices:
        # this is the menu's Turn Off entry, and it should put up what
        # every other way of turning the machine off puts up.
        from src.shell.shutdown_dialog import show_shutdown_dialog
        show_shutdown_dialog(self.GetParent())

    @staticmethod
    def _titan_items(kind):
        try:
            if kind == 'applications':
                from src.titan_core.app_manager import get_applications
                return [app.get('name', '') for app in get_applications()]
            from src.titan_core.game_manager import get_games
            return [game.get('name', '') for game in get_games()]
        except Exception:
            return []

    def _starter(self, kind, name):
        def start():
            try:
                if kind == 'app':
                    from src.titan_core.app_manager import (get_applications,
                                                            open_application)
                    match = next((a for a in get_applications()
                                  if a.get('name') == name), None)
                    if match:
                        open_application(match)
                else:
                    from src.titan_core.game_manager import get_games, open_game
                    match = next((g for g in get_games()
                                  if g.get('name') == name), None)
                    if match:
                        open_game(match)
            except Exception as error:
                self.api.log(f"could not start {name}: {error}")
        return start

    def _fill(self, needle=''):
        needle = (needle or '').strip().lower()
        self._entries = [entry for entry in self._build_entries()
                         if not needle or needle in entry[0].lower()]
        self.list.Set([label for label, _action in self._entries])
        if self._entries:
            self.list.SetSelection(0)

    # -- using it --------------------------------------------------------
    def _filter(self, _event):
        self._fill(self.search.GetValue())

    def _activate(self, _event=None):
        index = self.list.GetSelection()
        if index == wx.NOT_FOUND or index >= len(self._entries):
            return
        action = self._entries[index][1]
        self.Hide()
        try:
            action()
        except Exception as error:
            self.api.log(f"entry failed: {error}")

    def _on_key(self, event):
        key = event.GetKeyCode()
        if key == wx.WXK_ESCAPE:
            self.Hide()
            return
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) \
                and self.FindFocus() is self.list:
            self._activate()
            return
        # Typing goes to the search box wherever the keyboard is, which is
        # what a Start menu does.
        if self.FindFocus() is self.list and key in (wx.WXK_DOWN, wx.WXK_UP):
            event.Skip()
            return
        event.Skip()

    def _on_activate(self, event):
        # A Start menu that has lost the keyboard has been dismissed.
        if not event.GetActive() and self.IsShown():
            wx.CallAfter(self.Hide)
        event.Skip()

    def _on_close(self, event):
        # Furniture, not a document: Alt+F4 puts it away rather than
        # destroying it, or the shell would be left holding a dead window.
        self.Hide()
        event.Veto()

    # -- what the shell asks of it ---------------------------------------
    def show_menu(self):
        """Called by `TitanShell.toggle_start_menu`, if it is there."""
        self._fill()
        self.search.SetValue('')
        display = wx.Display().GetClientArea()
        self.SetPosition((display.x, display.y + display.height - MENU_HEIGHT))
        self.Show()
        self.Raise()
        try:
            from src.shell.win_shell import take_foreground
            take_foreground(self.GetHandle())
        except Exception:
            pass
        self.list.SetFocus()


def open_start_menu(api, parent):
    """What makes this add-on a Start menu provider."""
    return SimpleStartMenu(api, parent)
