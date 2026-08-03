# -*- coding: utf-8 -*-
"""The accessible WhatsApp client for Titan IM.

WhatsApp Web runs offscreen as the engine (``im_web.whatsapp_backend``); this
window is what the user actually uses. Same interaction as Titan-Net, Elten and
the Feedback Hub: a top tab bar in row 0, Left/Right to cycle it, Enter to open,
Escape to go back, F5 to refresh, stereo focus cues and the Titan-Net sound set.

Logging in never shows a QR code: Titan asks WhatsApp for the eight-character
link-device code and reads it out. The raw page is only ever brought on screen
when the user asks for it.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple

import wx

from src.network.im_client_base import TAB_CALLS, WebIMClientFrame
from src.network.im_ui_common import (
    _, apply_skin_tree, show_message, speak_notification, speak_titannet,
)
from src.network.im_web.base import CAP_CHANNELS, CAP_STATUS_UPDATES
from src.network.im_web.whatsapp_backend import get_whatsapp_backend

TAB_CHATS = 'chats'
TAB_UNREAD = 'unread'
TAB_GROUPS = 'groups'
TAB_CHANNELS = 'channels'
TAB_STATUS = 'status'
TAB_ARCHIVED = 'archived'


class WhatsAppPhoneDialog(wx.Dialog):
    """Ask for the phone number the pairing code should be issued for."""

    def __init__(self, parent, default_phone: str = ''):
        super().__init__(parent, title=_("Log in to WhatsApp"), size=(460, 240))

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(panel, label=_(
            "Enter the phone number of the WhatsApp account, with the country "
            "code and no spaces, for example 48123456789.\n"
            "Titan will show an eight-character code to type on your phone.")),
            flag=wx.ALL, border=10)

        sizer.Add(wx.StaticText(panel, label=_("Phone number:")),
                  flag=wx.LEFT | wx.RIGHT, border=10)
        self.phone = wx.TextCtrl(panel, value=default_phone)
        sizer.Add(self.phone, flag=wx.EXPAND | wx.ALL, border=10)

        self.remember = wx.CheckBox(panel, label=_("Remember this number"))
        self.remember.SetValue(True)
        sizer.Add(self.remember, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        ok = wx.Button(panel, wx.ID_OK, _("Get the code"))
        ok.SetDefault()
        buttons.Add(ok, flag=wx.RIGHT, border=8)
        buttons.Add(wx.Button(panel, wx.ID_CANCEL, _("Cancel")))
        sizer.Add(buttons, flag=wx.ALL | wx.ALIGN_RIGHT, border=10)

        panel.SetSizer(sizer)
        apply_skin_tree(self)
        self.Centre()
        self.phone.SetFocus()

    @property
    def phone_number(self) -> str:
        return ''.join(ch for ch in self.phone.GetValue() if ch.isdigit())


class WhatsAppClientFrame(WebIMClientFrame):
    """WhatsApp's own client window."""

    SERVICE_TITLE = _("WhatsApp - Titan IM")
    LIST_LABEL = _("Conversations:")
    VIEW_ID = 'titan_im_whatsapp'

    def build_tabs(self) -> Sequence[Tuple[str, str]]:
        tabs = [
            (TAB_CHATS, _("Chats")),
            (TAB_UNREAD, _("Unread")),
            (TAB_GROUPS, _("Groups")),
        ]
        if self.backend.has(CAP_CHANNELS):
            tabs.append((TAB_CHANNELS, _("Channels")))
        if self.backend.has(CAP_STATUS_UPDATES):
            tabs.append((TAB_STATUS, _("Status updates")))
        tabs.append((TAB_CALLS, _("Calls")))
        tabs.append((TAB_ARCHIVED, _("Archived")))
        return tabs

    def scope_for(self, tab_id: str) -> str:
        return {
            TAB_CHATS: 'chats',
            TAB_UNREAD: 'unread',
            TAB_GROUPS: 'groups',
            TAB_CHANNELS: 'channels',
            TAB_STATUS: 'status',
            TAB_ARCHIVED: 'archived',
        }.get(tab_id, 'all')

    def build_service_menu(self) -> Tuple[wx.Menu, str]:
        menu, _label = super().build_service_menu()
        return menu, _("&WhatsApp")

    # ------------------------------------------------------------------ login
    def start_login(self) -> None:
        from src.settings.titan_im_config import get_web_im_value, set_web_im_value

        remembered = ''
        try:
            remembered = get_web_im_value('whatsapp', 'phone', '') or ''
        except Exception as exc:
            print(f"[WhatsApp] could not read the remembered number: {exc}")

        dialog = WhatsAppPhoneDialog(self, remembered)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                speak_titannet(_("Login cancelled. WhatsApp needs a linked "
                                 "device to work."))
                return
            phone = dialog.phone_number
            remember = dialog.remember.GetValue()
        finally:
            dialog.Destroy()

        if not phone:
            speak_notification(_("No phone number given"), 'warning')
            return

        if remember:
            try:
                set_web_im_value('whatsapp', 'phone', phone)
            except Exception as exc:
                print(f"[WhatsApp] could not save the number: {exc}")

        speak_titannet(_("Asking WhatsApp for a pairing code..."))
        self.backend.request_pairing_code(phone, callback=self._on_pairing_result)

    def _on_pairing_result(self, result: Dict) -> None:
        if not result.get('success'):
            answer = show_message(
                self,
                _("WhatsApp did not return a pairing code.\nError: {error}\n\n"
                  "Show the web page so you can log in there instead?").format(
                      error=result.get('error') or ''),
                _("Login"), wx.YES_NO | wx.ICON_WARNING)
            if answer == wx.ID_YES:
                self.show_web_page()
            return

        code = result.get('pairing_code') or ''
        if code:
            self.show_pairing_code(code)
        else:
            speak_titannet(_("Waiting for the pairing code..."))

    def show_pairing_code(self, code: str) -> None:
        speak_titannet(_("Pairing code: {code}").format(code=' '.join(code)))
        show_message(
            self,
            _("Enter this code on your phone:\n\n{code}\n\n"
              "On the phone: WhatsApp, Settings, Linked devices, Link a device, "
              "then \"Link with phone number instead\".").format(code=code),
            _("WhatsApp pairing code"))


_frame: Optional[WhatsAppClientFrame] = None


def show_whatsapp_client(parent=None) -> Optional[WhatsAppClientFrame]:
    """Open (or raise) the accessible WhatsApp client, starting the engine."""
    global _frame

    if _frame is not None:
        try:
            _frame.Raise()
            _frame.SetFocus()
            return _frame
        except Exception:
            _frame = None

    from src.network.im_web.bridge import WebBridgeUnavailable, is_available
    if not is_available():
        show_message(parent, _("WhatsApp needs Microsoft WebView2, which is not "
                               "installed on this computer."),
                     _("WhatsApp"), wx.OK | wx.ICON_ERROR)
        return None

    try:
        backend = get_whatsapp_backend()
    except WebBridgeUnavailable as exc:
        show_message(parent, str(exc), _("WhatsApp"), wx.OK | wx.ICON_ERROR)
        return None

    frame = WhatsAppClientFrame(parent, backend)

    def _forget(event):
        global _frame
        _frame = None
        event.Skip()

    frame.Bind(wx.EVT_CLOSE, _forget)
    frame.Show()
    frame.listbox.SetFocus()
    _frame = frame
    return frame


def get_whatsapp_client() -> Optional[WhatsAppClientFrame]:
    return _frame
