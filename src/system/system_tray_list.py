# -*- coding: utf-8 -*-
"""
System Tray List - Accessible system tray icon browser
Shows system tray icons in a list with keyboard navigation
(Windows only)
"""

import wx
import platform
from src.titan_core.sound import play_sound
from src.controller.controller_vibrations import vibrate_cursor_move, vibrate_selection, vibrate_menu_open
from src.titan_core.translation import _
from src.settings.settings import get_setting
from src.platform_utils import IS_WINDOWS

# Windows-specific imports
if IS_WINDOWS:
    import win32gui
    import win32con
    import win32api
    import ctypes
    from ctypes import wintypes
    import struct


# Constants for system tray
WM_USER = 0x0400
TB_BUTTONCOUNT = WM_USER + 24
TB_GETBUTTON = WM_USER + 23
TB_GETBUTTONTEXTW = WM_USER + 75

# Shell_NotifyIcon messages
NIN_SELECT = WM_USER + 0
NIN_KEYSELECT = WM_USER + 1
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B


class TBBUTTON(ctypes.Structure):
    """Toolbar button structure"""
    _fields_ = [
        ('iBitmap', ctypes.c_int),
        ('idCommand', ctypes.c_int),
        ('fsState', ctypes.c_byte),
        ('fsStyle', ctypes.c_byte),
        ('bReserved', ctypes.c_byte * 6),
        ('dwData', ctypes.POINTER(ctypes.c_ulong)),
        ('iString', ctypes.POINTER(ctypes.c_char))
    ]


class SystemTrayIcon:
    """Represents a system tray icon"""
    def __init__(self, hwnd, button_id, text, tooltip):
        self.hwnd = hwnd
        self.button_id = button_id
        self.text = text or _("Unknown Icon")
        self.tooltip = tooltip or self.text

    def left_click(self):
        """Simulate left click on icon"""
        try:
            # Get icon position
            rect = win32gui.GetWindowRect(self.hwnd)
            x = rect[0] + 10
            y = rect[1] + 10

            # Send mouse messages to simulate click
            lParam = win32api.MAKELONG(x, y)
            win32gui.PostMessage(self.hwnd, WM_LBUTTONUP, 0, lParam)
            print(f"INFO: Left clicked on tray icon: {self.text}")
        except Exception as e:
            print(f"ERROR: Failed to left click tray icon: {e}")

    def right_click(self):
        """Simulate right click on icon to show context menu"""
        try:
            # Get icon position
            rect = win32gui.GetWindowRect(self.hwnd)
            x = rect[0] + 10
            y = rect[1] + 10

            # Send right button up message to trigger context menu
            lParam = win32api.MAKELONG(x, y)
            win32gui.PostMessage(self.hwnd, WM_RBUTTONUP, 0, lParam)

            # Also send WM_CONTEXTMENU for better compatibility
            win32gui.PostMessage(self.hwnd, WM_CONTEXTMENU, self.hwnd, lParam)
            print(f"INFO: Right clicked on tray icon: {self.text}")
        except Exception as e:
            print(f"ERROR: Failed to right click tray icon: {e}")


def find_system_tray_window():
    """Find the system tray window (notification area)"""
    try:
        # Find Shell_TrayWnd (taskbar)
        tray_wnd = win32gui.FindWindow("Shell_TrayWnd", None)
        if not tray_wnd:
            print("WARNING: Shell_TrayWnd not found")
            return None

        # Find TrayNotifyWnd
        tray_notify = win32gui.FindWindowEx(tray_wnd, 0, "TrayNotifyWnd", None)
        if not tray_notify:
            print("WARNING: TrayNotifyWnd not found")
            return None

        # Try to find SysPager (older Windows versions)
        sys_pager = win32gui.FindWindowEx(tray_notify, 0, "SysPager", None)

        # Find ToolbarWindow32 (the actual toolbar with icons)
        if sys_pager:
            # Older Windows (Vista, 7, 8, early 10)
            print("INFO: Using SysPager for system tray (older Windows)")
            toolbar = win32gui.FindWindowEx(sys_pager, 0, "ToolbarWindow32", None)
        else:
            # Newer Windows 10/11 - try directly under TrayNotifyWnd
            print("INFO: SysPager not found, trying direct TrayNotifyWnd (newer Windows 10/11)")
            toolbar = win32gui.FindWindowEx(tray_notify, 0, "ToolbarWindow32", None)

        if toolbar:
            print(f"INFO: Found system tray toolbar: {toolbar}")
            return toolbar
        else:
            print("WARNING: ToolbarWindow32 not found in system tray")
            return None

    except Exception as e:
        print(f"ERROR: Failed to find system tray window: {e}")
        import traceback
        traceback.print_exc()
        return None


def find_overflow_tray_window():
    """Find the overflow (hidden) system tray window"""
    try:
        # In Windows 10/11, overflow icons are in NotifyIconOverflowWindow
        overflow_wnd = win32gui.FindWindow("NotifyIconOverflowWindow", None)
        if not overflow_wnd:
            print("INFO: NotifyIconOverflowWindow not found (no hidden icons or older Windows)")
            return None

        # Find the toolbar in overflow window
        toolbar = win32gui.FindWindowEx(overflow_wnd, 0, "ToolbarWindow32", None)
        if toolbar:
            print(f"INFO: Found overflow tray toolbar: {toolbar}")
        else:
            print("WARNING: ToolbarWindow32 not found in overflow window")

        return toolbar

    except Exception as e:
        print(f"WARNING: Failed to find overflow tray window: {e}")
        return None


def get_tray_icons():
    """Get list of system tray icons (visible and hidden)"""
    icons = []

    # Get visible tray icons
    try:
        toolbar_hwnd = find_system_tray_window()
        if toolbar_hwnd:
            # Get button count
            button_count = win32gui.SendMessage(toolbar_hwnd, TB_BUTTONCOUNT, 0, 0)
            print(f"INFO: Found {button_count} visible tray icons")

            # Get each button/icon info
            for i in range(button_count):
                try:
                    # Get button text (tooltip)
                    text_buffer = ctypes.create_unicode_buffer(256)
                    text_length = win32gui.SendMessage(toolbar_hwnd, TB_GETBUTTONTEXTW, i, ctypes.addressof(text_buffer))

                    if text_length > 0:
                        tooltip = text_buffer.value
                    else:
                        tooltip = _("System Icon") + f" {i+1}"

                    # Create icon object
                    icon = SystemTrayIcon(
                        hwnd=toolbar_hwnd,
                        button_id=i,
                        text=tooltip,
                        tooltip=tooltip
                    )
                    icons.append(icon)

                except Exception as e:
                    print(f"WARNING: Failed to get info for visible icon {i}: {e}")
                    # Add placeholder icon
                    icon = SystemTrayIcon(
                        hwnd=toolbar_hwnd,
                        button_id=i,
                        text=_("System Icon") + f" {i+1}",
                        tooltip=_("Unknown")
                    )
                    icons.append(icon)
        else:
            print("WARNING: Visible system tray window not found")

    except Exception as e:
        print(f"ERROR: Failed to get visible tray icons: {e}")

    # Get hidden/overflow tray icons
    try:
        overflow_hwnd = find_overflow_tray_window()
        if overflow_hwnd:
            # Get button count in overflow
            button_count = win32gui.SendMessage(overflow_hwnd, TB_BUTTONCOUNT, 0, 0)
            print(f"INFO: Found {button_count} hidden/overflow tray icons")

            # Get each button/icon info
            for i in range(button_count):
                try:
                    # Get button text (tooltip)
                    text_buffer = ctypes.create_unicode_buffer(256)
                    text_length = win32gui.SendMessage(overflow_hwnd, TB_GETBUTTONTEXTW, i, ctypes.addressof(text_buffer))

                    if text_length > 0:
                        tooltip = text_buffer.value
                        # Add marker to indicate it's a hidden icon
                        tooltip = f"[{_('Hidden')}] {tooltip}"
                    else:
                        tooltip = f"[{_('Hidden')}] " + _("System Icon") + f" {i+1}"

                    # Create icon object
                    icon = SystemTrayIcon(
                        hwnd=overflow_hwnd,
                        button_id=i,
                        text=tooltip,
                        tooltip=tooltip
                    )
                    icons.append(icon)

                except Exception as e:
                    print(f"WARNING: Failed to get info for hidden icon {i}: {e}")
                    # Add placeholder icon
                    icon = SystemTrayIcon(
                        hwnd=overflow_hwnd,
                        button_id=i,
                        text=f"[{_('Hidden')}] " + _("System Icon") + f" {i+1}",
                        tooltip=_("Unknown")
                    )
                    icons.append(icon)

    except Exception as e:
        print(f"WARNING: Failed to get hidden/overflow tray icons: {e}")

    print(f"INFO: Total tray icons found: {len(icons)}")
    return icons


class SystemTrayListDialog(wx.Dialog):
    """Dialog showing system tray icons in a list"""

    def __init__(self, parent):
        super().__init__(parent, title=_("System Tray"),
                        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self.icons = []
        self.init_ui()
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

    def load_icons(self):
        """Load system tray icons into the list"""
        self.icons = get_tray_icons()

        self.icon_list.Clear()

        if not self.icons:
            self.icon_list.Append(_("No system tray icons found"))
            self.click_button.Enable(False)
            self.context_button.Enable(False)
        else:
            for icon in self.icons:
                self.icon_list.Append(icon.text)

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
        if icon:
            play_sound('select.ogg')
            vibrate_selection()
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
        wx.MessageBox(
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
