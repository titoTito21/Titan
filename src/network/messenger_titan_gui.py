# -*- coding: utf-8 -*-
"""The accessible Messenger client for Titan IM.

messenger.com runs offscreen as the engine (``im_web.messenger_backend``) and
this window is the interface: top tab bar in row 0, Left/Right to cycle,
Enter to open, Escape to go back, F5 to refresh, stereo focus cues, Titan-Net
sounds - the same as Titan-Net, Elten and the WhatsApp client.

Logging in happens in a normal Titan dialog whose values are typed into
Messenger's own form. Only a checkpoint, two-factor prompt or captcha brings the
real page on screen, because those cannot be answered blind.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple

import wx

from src.network.im_client_base import TAB_CALLS, WebIMClientFrame
from src.network.im_ui_common import (
    _, apply_skin_tree, show_message, speak_notification, speak_titannet,
)
from src.network.im_web.base import CAP_MESSAGE_REQUESTS
from src.network.im_web.messenger_backend import get_messenger_backend

TAB_CHATS = 'chats'
TAB_UNREAD = 'unread'
TAB_GROUPS = 'groups'
TAB_ACTIVE = 'active'
TAB_REQUESTS = 'requests'


class MessengerLoginDialog(wx.Dialog):
    """E-mail and password, typed into Messenger's own login form for us."""

    def __init__(self, parent, default_email: str = '',
                 default_password: str = ''):
        super().__init__(parent, title=_("Log in to Messenger"), size=(470, 300))

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(panel, label=_(
            "Enter your Facebook credentials. Titan fills in the Messenger login "
            "form for you - nothing is sent anywhere else.\n"
            "If Facebook asks for an extra confirmation, Titan will offer to show "
            "the page so you can finish it.")), flag=wx.ALL, border=10)

        sizer.Add(wx.StaticText(panel, label=_("E-mail address or phone number:")),
                  flag=wx.LEFT | wx.RIGHT, border=10)
        self.email = wx.TextCtrl(panel, value=default_email)
        sizer.Add(self.email, flag=wx.EXPAND | wx.ALL, border=10)

        sizer.Add(wx.StaticText(panel, label=_("Password:")),
                  flag=wx.LEFT | wx.RIGHT, border=10)
        self.password = wx.TextCtrl(panel, value=default_password,
                                    style=wx.TE_PASSWORD)
        sizer.Add(self.password, flag=wx.EXPAND | wx.ALL, border=10)

        self.remember = wx.CheckBox(panel, label=_(
            "Remember the e-mail address and the password"))
        # Ticked by default, and already ticked when there is something saved.
        self.remember.SetValue(True)
        sizer.Add(self.remember, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        sizer.Add(wx.StaticText(panel, label=_(
            "The password is kept in the encrypted Titan IM file, the same "
            "place as the other messenger credentials.")),
            flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=10)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        ok = wx.Button(panel, wx.ID_OK, _("Log in"))
        ok.SetDefault()
        buttons.Add(ok, flag=wx.RIGHT, border=8)
        buttons.Add(wx.Button(panel, wx.ID_CANCEL, _("Cancel")))
        sizer.Add(buttons, flag=wx.ALL | wx.ALIGN_RIGHT, border=10)

        panel.SetSizer(sizer)
        apply_skin_tree(self)
        self.Centre()
        self.email.SetFocus()


class MessengerClientFrame(WebIMClientFrame):
    """Messenger's own client window."""

    SERVICE_TITLE = _("Messenger - Titan IM")
    LIST_LABEL = _("Conversations:")
    VIEW_ID = 'titan_im_messenger'

    def build_tabs(self) -> Sequence[Tuple[str, str]]:
        tabs = [
            (TAB_CHATS, _("Chats")),
            (TAB_UNREAD, _("Unread")),
            (TAB_GROUPS, _("Groups")),
            (TAB_ACTIVE, _("Active now")),
        ]
        if self.backend.has(CAP_MESSAGE_REQUESTS):
            tabs.append((TAB_REQUESTS, _("Message requests")))
        tabs.append((TAB_CALLS, _("Calls")))
        return tabs

    def scope_for(self, tab_id: str) -> str:
        return {
            TAB_CHATS: 'all',
            TAB_UNREAD: 'unread',
            TAB_GROUPS: 'groups',
            TAB_ACTIVE: 'active',
            TAB_REQUESTS: 'requests',
        }.get(tab_id, 'all')

    def build_service_menu(self) -> Tuple[wx.Menu, str]:
        menu, _label = super().build_service_menu()
        return menu, _("&Messenger")

    # ------------------------------------------------------------------ login
    def start_login(self) -> None:
        from src.settings.titan_im_config import get_web_im_value, set_web_im_value

        remembered = ''
        remembered_password = ''
        try:
            remembered = get_web_im_value('messenger', 'email', '') or ''
            remembered_password = get_web_im_value('messenger', 'password', '') or ''
        except Exception as exc:
            print(f"[Messenger] could not read the remembered credentials: {exc}")

        dialog = MessengerLoginDialog(self, remembered, remembered_password)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                speak_titannet(_("Login cancelled."))
                return
            email = dialog.email.GetValue().strip()
            password = dialog.password.GetValue()
            remember = dialog.remember.GetValue()
        finally:
            dialog.Destroy()

        if not email or not password:
            speak_notification(_("Both the e-mail address and the password are needed"),
                               'warning')
            return

        # Remembering means both halves: an e-mail without its password still
        # makes the user type the password on every single login.
        try:
            set_web_im_value('messenger', 'email', email if remember else '')
            set_web_im_value('messenger', 'password', password if remember else '')
        except Exception as exc:
            print(f"[Messenger] could not save the credentials: {exc}")

        speak_titannet(_("Logging in to Messenger..."))
        self.backend.login_with_credentials(email, password,
                                            callback=self._on_login_result)

    def _on_login_result(self, result: Dict) -> None:
        # The agent pushes the auth state before this result comes back, so the
        # question about showing the page may already have been asked - it goes
        # through ask_to_show_page, which asks at most once per challenge.
        if not result.get('success'):
            self.ask_to_show_page(
                _("Messenger login failed.\nError: {error}\n\n"
                  "Show the web page so you can log in there instead?").format(
                      error=result.get('error') or ''))
            return

        if result.get('needs_page'):
            self.ask_to_show_page(
                _("Facebook is asking for an extra confirmation (a code, a "
                  "captcha or a device check).\nShow the page so you can finish "
                  "logging in?"))
            return

        speak_notification(_("Connected to Messenger"), 'success')
        self.refresh()


_frame: Optional[MessengerClientFrame] = None


def show_messenger_client(parent=None) -> Optional[MessengerClientFrame]:
    """Open (or raise) the accessible Messenger client, starting the engine."""
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
        show_message(parent, _("Messenger needs Microsoft WebView2, which is not "
                               "installed on this computer."),
                     _("Messenger"), wx.OK | wx.ICON_ERROR)
        return None

    try:
        backend = get_messenger_backend()
    except WebBridgeUnavailable as exc:
        show_message(parent, str(exc), _("Messenger"), wx.OK | wx.ICON_ERROR)
        return None

    frame = MessengerClientFrame(parent, backend)

    def _forget(event):
        global _frame
        _frame = None
        event.Skip()

    frame.Bind(wx.EVT_CLOSE, _forget)
    frame.Show()
    frame.listbox.SetFocus()
    _frame = frame
    return frame


def get_messenger_client() -> Optional[MessengerClientFrame]:
    return _frame
