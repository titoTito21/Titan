# -*- coding: utf-8 -*-
"""
System Tray List - Accessible system tray icon browser
Shows system tray icons in a list with keyboard navigation
(Windows only)

The icons themselves are read by `src.system.tray_icons`, which knows how to
ask both the Windows 11 taskbar (UI Automation) and the older toolbar one.
This module is the window over that.
"""

import wx

from src.titan_core.sound import play_sound
from src.controller.controller_vibrations import (vibrate_cursor_move,
                                                  vibrate_selection,
                                                  vibrate_menu_open)
from src.titan_core.translation import _
from src.platform_utils import IS_WINDOWS
from src.titan_core.skin_manager import apply_skin_to_window
from src.system.tray_icons import (SystemTrayIcon, expand_hidden_icons,
                                   get_tray_icons, is_chevron)

__all__ = ['SystemTrayIcon', 'get_tray_icons', 'expand_hidden_icons',
           'is_chevron', 'show_system_tray_list', 'SystemTrayListDialog']


def _apply_skin_to_tree(window):
    try:
        apply_skin_to_window(window)
    except Exception:
        return
    for child in window.GetChildren():
        _apply_skin_to_tree(child)


def _show_skinned_message(message, caption, style=wx.OK | wx.ICON_INFORMATION, parent=None):
    dlg = wx.MessageDialog(parent, message, caption, style)
    _apply_skin_to_tree(dlg)
    result = dlg.ShowModal()
    dlg.Destroy()
    return result


class SystemTrayListDialog(wx.Dialog):
    """Dialog showing system tray icons in a list"""

    def __init__(self, parent):
        super().__init__(parent, title=_("System Tray"),
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self.icons = []
        self.init_ui()
        _apply_skin_to_tree(self)
        self.load_icons()

        # Play sound when opening
        play_sound('focus.ogg')
        vibrate_menu_open()

        self.SetSize((400, 300))
        self.Centre()

    def init_ui(self):
        """Initialize the user interface"""
        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Info label
        info_label = wx.StaticText(panel, label=_("System Tray Icons (Enter = click, Applications key/Context menu = right click)"))
        vbox.Add(info_label, flag=wx.ALL | wx.EXPAND, border=10)

        # List of icons
        self.icon_list = wx.ListBox(panel, style=wx.LB_SINGLE)
        self.icon_list.Bind(wx.EVT_LISTBOX, self.on_selection_changed)
        self.icon_list.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
        vbox.Add(self.icon_list, proportion=1, flag=wx.ALL | wx.EXPAND, border=10)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.click_button = wx.Button(panel, label=_("Click (Enter)"))
        self.click_button.Bind(wx.EVT_BUTTON, self.on_click)
        button_sizer.Add(self.click_button, flag=wx.ALL, border=5)

        self.context_button = wx.Button(panel, label=_("Context Menu (Applications key)"))
        self.context_button.Bind(wx.EVT_BUTTON, self.on_context_menu)
        button_sizer.Add(self.context_button, flag=wx.ALL, border=5)

        close_button = wx.Button(panel, wx.ID_CLOSE, _("Close"))
        close_button.Bind(wx.EVT_BUTTON, self.on_close)
        button_sizer.Add(close_button, flag=wx.ALL, border=5)

        vbox.Add(button_sizer, flag=wx.ALL | wx.ALIGN_CENTER, border=10)

        panel.SetSizer(vbox)

        # Bind dialog events
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def load_icons(self, expand_hidden=False):
        """Load system tray icons into the list"""
        if expand_hidden:
            hidden = expand_hidden_icons()
            visible = [icon for icon in get_tray_icons(include_hidden=False)
                       if not is_chevron(icon)]
            self.icons = visible + hidden
        else:
            self.icons = get_tray_icons()

        self.icon_list.Clear()

        if not self.icons:
            self.icon_list.Append(_("No system tray icons found"))
            self.click_button.Enable(False)
            self.context_button.Enable(False)
        else:
            for icon in self.icons:
                label = icon.text
                if icon.hidden:
                    label = "{} ({})".format(label, _("hidden"))
                self.icon_list.Append(label)

            # Select first item
            if self.icon_list.GetCount() > 0:
                self.icon_list.SetSelection(0)
                self.icon_list.SetFocus()

    def get_selected_icon(self):
        """Get the currently selected icon"""
        selection = self.icon_list.GetSelection()
        if selection != wx.NOT_FOUND and selection < len(self.icons):
            return self.icons[selection]
        return None

    def on_selection_changed(self, event):
        """Handle selection change"""
        play_sound('focus.ogg')
        vibrate_cursor_move()

    def on_click(self, event):
        """Handle click button / Enter key"""
        icon = self.get_selected_icon()
        if not icon:
            return
        play_sound('select.ogg')
        vibrate_selection()
        if is_chevron(icon):
            # "Show hidden icons" is not something to leave the list for:
            # the hidden icons belong in this list, so it opens them and
            # shows them here instead of closing and leaving a flyout open.
            self.load_icons(expand_hidden=True)
            return
        icon.left_click()
        # Close dialog after click
        wx.CallLater(100, self.Close)

    def on_context_menu(self, event):
        """Handle context menu button / Applications key"""
        icon = self.get_selected_icon()
        if icon:
            play_sound('select.ogg')
            vibrate_selection()
            icon.right_click()
            # Close dialog after opening context menu
            wx.CallLater(100, self.Close)

    def on_key_down(self, event):
        """Handle keyboard shortcuts"""
        keycode = event.GetKeyCode()

        if keycode == wx.WXK_RETURN or keycode == wx.WXK_NUMPAD_ENTER:
            # Enter = left click
            self.on_click(event)
        elif keycode == wx.WXK_WINDOWS_MENU or keycode == wx.WXK_MENU:
            # Applications key / Menu key = context menu
            self.on_context_menu(event)
        elif keycode == wx.WXK_ESCAPE:
            # Escape = close
            self.Close()
        else:
            event.Skip()

    def on_close(self, event):
        """Handle close event"""
        play_sound('dialogclose.ogg')
        self.Destroy()


def show_system_tray_list(parent):
    """Show the system tray list dialog (Windows only)"""
    if not IS_WINDOWS:
        _show_skinned_message(
            _("System tray list is only available on Windows"),
            _("Not Available"),
            wx.OK | wx.ICON_INFORMATION
        )
        return

    try:
        dialog = SystemTrayListDialog(parent)
        dialog.Show()
    except Exception as e:
        print(f"ERROR: Failed to show system tray list: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    # Test the system tray list
    app = wx.App()
    show_system_tray_list(None)
    app.MainLoop()

