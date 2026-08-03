# -*- coding: utf-8 -*-
"""Call windows for the Titan IM web clients.

The audio never leaves the page - WhatsApp Web and Messenger own the WebRTC
session, and reimplementing that would be pointless. These windows are the
*control surface*: they announce a ringing call, accept or end it through the
backend, and count the duration out loud on request.

Call state comes from the agent, which drains
``src/network/call_detection_js.py``'s state machine - the one written to stop
the phantom "incoming call" that the old polling integrations produced. A call
exists only when a control that can exist only during a live call is on the
page, so opening a conversation no longer rings.

Interaction follows the Telegram call windows (``telegram_windows.py``): Enter
accepts, Escape rejects or hangs up, Space says how long the call has been
running.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import wx

from src.network.im_web.base import EV_CALL, CallState
from src.network.im_ui_common import _, apply_skin_tree, sounds, speak_titannet
from src.titan_core.sound import play_sound


class IncomingCallDialog(wx.Dialog):
    """Ringing call: Enter accepts, Escape declines."""

    RING_INTERVAL_MS = 3000

    def __init__(self, parent, backend, call: CallState):
        super().__init__(parent, title=_("Incoming call"), size=(420, 200))
        self.backend = backend
        self.call = call
        self.answered = False

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        kind = _("Video call") if call.video else _("Voice call")
        caller = call.peer or _("Unknown caller")
        self.label = wx.StaticText(
            panel, label=_("{kind} from {caller}").format(kind=kind, caller=caller))
        sizer.Add(self.label, flag=wx.ALL, border=12)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.accept_button = wx.Button(panel, label=_("Answer"))
        self.accept_button.Bind(wx.EVT_BUTTON, lambda e: self._accept())
        buttons.Add(self.accept_button, flag=wx.RIGHT, border=8)

        self.reject_button = wx.Button(panel, label=_("Decline"))
        self.reject_button.Bind(wx.EVT_BUTTON, lambda e: self._reject())
        buttons.Add(self.reject_button)
        sizer.Add(buttons, flag=wx.ALL, border=12)

        panel.SetSizer(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        apply_skin_tree(self)
        self.Centre()

        self._ring_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self._ring(), self._ring_timer)
        self._ring()
        self._ring_timer.Start(self.RING_INTERVAL_MS)

        speak_titannet(_("{kind} from {caller}").format(kind=kind, caller=caller))
        self.accept_button.SetFocus()

    def _ring(self) -> None:
        if sounds:
            try:
                sounds.ring_incoming()
            except Exception:
                pass

    def _stop_ringing(self) -> None:
        if self._ring_timer.IsRunning():
            self._ring_timer.Stop()

    def _accept(self) -> None:
        self.answered = True
        self._stop_ringing()
        self.backend.accept_call()
        self.EndModal(wx.ID_OK)

    def _reject(self) -> None:
        self._stop_ringing()
        self.backend.end_call()
        self.EndModal(wx.ID_CANCEL)

    def _on_key(self, event: wx.KeyEvent) -> None:
        keycode = event.GetKeyCode()
        if keycode in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._accept()
            return
        if keycode == wx.WXK_ESCAPE:
            self._reject()
            return
        event.Skip()

    def close_quietly(self) -> None:
        """The other side gave up - stop ringing without acting on the call."""
        self._stop_ringing()
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.Destroy()


class ActiveCallFrame(wx.Frame):
    """A live (or ringing out) call: Escape hangs up, Space reads the duration."""

    def __init__(self, parent, backend, call: CallState):
        super().__init__(parent, title=_("Call"), size=(420, 220))
        self.backend = backend
        self.call = call
        self.started_at = call.started_at or time.time()
        self.connected = (call.state == 'connected')

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.peer_label = wx.StaticText(panel, label=call.peer or _("Unknown"))
        sizer.Add(self.peer_label, flag=wx.ALL, border=12)

        self.state_label = wx.StaticText(panel, label=self._state_text())
        sizer.Add(self.state_label, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=12)

        self.end_button = wx.Button(panel, label=_("End call"))
        self.end_button.Bind(wx.EVT_BUTTON, lambda e: self._end())
        sizer.Add(self.end_button, flag=wx.ALL, border=12)

        panel.SetSizer(sizer)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        apply_skin_tree(self)
        self.Centre()

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self._tick(), self._timer)
        self._timer.Start(1000)

        if not self.connected and sounds:
            try:
                sounds.ring_outgoing()
            except Exception:
                pass

        speak_titannet(self._state_text())
        self.end_button.SetFocus()

    # ------------------------------------------------------------------ state
    def _state_text(self) -> str:
        kind = _("Video call") if self.call.video else _("Voice call")
        peer = self.call.peer or _("Unknown")
        if self.connected:
            return _("{kind} with {peer}, {duration}").format(
                kind=kind, peer=peer, duration=self._duration_text())
        if self.call.state == 'ringing_out':
            return _("{kind} to {peer}: ringing").format(kind=kind, peer=peer)
        return _("{kind} with {peer}").format(kind=kind, peer=peer)

    def _duration_text(self) -> str:
        seconds = max(0, int(time.time() - self.started_at))
        return _("{minutes} min {seconds} s").format(minutes=seconds // 60,
                                                     seconds=seconds % 60)

    def _tick(self) -> None:
        self.state_label.SetLabel(self._state_text())

    def update_state(self, call: CallState) -> None:
        was_connected = self.connected
        self.call = call
        self.connected = (call.state == 'connected')
        if self.connected and not was_connected:
            self.started_at = call.started_at or time.time()
            if sounds:
                try:
                    sounds.call_connected()
                except Exception:
                    pass
            speak_titannet(_("Call connected"))
        self._tick()

    # ------------------------------------------------------------------- keys
    def _on_key(self, event: wx.KeyEvent) -> None:
        keycode = event.GetKeyCode()
        if keycode == wx.WXK_ESCAPE:
            self._end()
            return
        if keycode == wx.WXK_SPACE:
            speak_titannet(self._state_text())
            return
        event.Skip()

    def _end(self) -> None:
        self.backend.end_call()
        speak_titannet(_("Ending the call"))
        self.Close()

    def _on_close(self, event) -> None:
        if self._timer.IsRunning():
            self._timer.Stop()
        event.Skip()

    def finish(self, announce: bool = True) -> None:
        """The call ended on its own."""
        if self._timer.IsRunning():
            self._timer.Stop()
        if announce:
            try:
                play_sound('titannet/offline.ogg')
            except Exception:
                pass
            speak_titannet(_("Call ended, {duration}").format(
                duration=self._duration_text()) if self.connected
                else _("Call ended"))
        self.Destroy()


class CallController:
    """Turns backend call events into the right window, once per backend."""

    def __init__(self, backend, parent_provider):
        self.backend = backend
        self._parent_provider = parent_provider
        self.incoming: Optional[IncomingCallDialog] = None
        self.active: Optional[ActiveCallFrame] = None
        backend.add_listener(self._on_event)

    def detach(self) -> None:
        self.backend.remove_listener(self._on_event)
        self._dismiss_all(announce=False)

    # ------------------------------------------------------------------ events
    def _on_event(self, event_type: str, payload: Any) -> None:
        if event_type != EV_CALL or not isinstance(payload, dict):
            return
        call = payload.get('call')
        if not isinstance(call, CallState):
            return
        wx.CallAfter(self._handle, call)

    def _handle(self, call: CallState) -> None:
        parent = None
        try:
            parent = self._parent_provider()
        except Exception:
            parent = None

        if call.state == 'ringing_in':
            if self.incoming is not None or self.active is not None:
                return
            self.incoming = IncomingCallDialog(parent, self.backend, call)
            result = self.incoming.ShowModal()
            answered = self.incoming.answered
            self.incoming.Destroy()
            self.incoming = None
            if answered:
                self._show_active(parent, CallState(state='connected', peer=call.peer,
                                                    peer_id=call.peer_id,
                                                    video=call.video,
                                                    started_at=time.time()))
            return

        if call.state in ('ringing_out', 'connected'):
            if self.incoming is not None:
                self.incoming.close_quietly()
                self.incoming = None
            if self.active is None:
                self._show_active(parent, call)
            else:
                self.active.update_state(call)
            return

        if call.state == 'ended':
            self._dismiss_all(announce=True)

    def _show_active(self, parent, call: CallState) -> None:
        self.active = ActiveCallFrame(parent, self.backend, call)
        self.active.Bind(wx.EVT_CLOSE, self._on_active_closed)
        self.active.Show()
        self.active.Raise()

    def _on_active_closed(self, event) -> None:
        self.active = None
        event.Skip()

    def _dismiss_all(self, announce: bool) -> None:
        if self.incoming is not None:
            self.incoming.close_quietly()
            self.incoming = None
        if self.active is not None:
            active, self.active = self.active, None
            try:
                active.finish(announce=announce)
            except Exception:
                pass
