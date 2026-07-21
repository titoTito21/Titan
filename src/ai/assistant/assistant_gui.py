"""Accessible window for the Titan voice assistant (Perun / Melitele).

Talk (push-to-talk) records one utterance, runs the agent, and speaks the reply
in the persona's Gemini voice. Live mode holds a continuous spoken conversation.
A text box provides a keyboard fallback when no microphone is available. Risky
agent actions are confirmed per the AI Agent policy; Shift+Escape cancels a run
or ends a live session, exactly like the standalone agent.
"""

import threading

import wx

from src.ai import ai_provider
from src.ai.ai_agent import AgentCancelled
from src.ai.assistant import personas as personas_mod
from src.ai.assistant import voice_assistant
from src.titan_core.translation import set_language
from src.settings.settings import get_setting

_ = set_language(get_setting('language', 'pl'))

try:
    from src.titan_core.sound import play_sound
except Exception:
    def play_sound(*_a, **_k):
        pass


def _speak(text):
    try:
        from src.accessibility.messages import speak_sr_only
        speak_sr_only(str(text))
        return
    except Exception:
        pass
    try:
        from src.system.notifications import speak_notification
        speak_notification(str(text), 'info')
    except Exception:
        pass


_STATUS_LABELS = {
    'listening': _("Listening..."),
    'nothing_heard': _("I did not hear anything."),
    'transcribing': _("Transcribing..."),
    'thinking': _("Thinking..."),
    'speaking': _("Speaking..."),
    'live': _("Live conversation active."),
    'idle': _("Ready."),
}


class AssistantFrame(wx.Frame):
    def __init__(self, parent, persona):
        self.persona = persona
        lang = get_setting('language', 'pl')
        name = persona['name_pl'] if lang == 'pl' else persona['name_en']
        super().__init__(parent, title=_("Titan Assistant - {name}").format(name=name),
                         size=(720, 620))
        self._cancel = None
        self._running = False
        self._live = None

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        vbox.Add(wx.StaticText(panel, label=_("Conversation:")),
                 flag=wx.LEFT | wx.TOP, border=8)
        self.transcript = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.transcript.SetName(_("Conversation"))
        vbox.Add(self.transcript, proportion=1, flag=wx.EXPAND | wx.ALL, border=8)

        self.status = wx.StaticText(panel, label=_("Ready."))
        vbox.Add(self.status, flag=wx.LEFT | wx.RIGHT, border=8)

        vbox.Add(wx.StaticText(panel, label=_("Type instead of speaking (optional):")),
                 flag=wx.LEFT | wx.TOP, border=8)
        self.input = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.input.SetName(_("Type instead of speaking"))
        self.input.Bind(wx.EVT_TEXT_ENTER, self.on_send_text)
        vbox.Add(self.input, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=8)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        self.talk_btn = wx.Button(panel, label=_("Talk"))
        self.talk_btn.Bind(wx.EVT_BUTTON, self.on_talk)
        btns.Add(self.talk_btn, flag=wx.RIGHT, border=6)
        self.send_btn = wx.Button(panel, label=_("Send text"))
        self.send_btn.Bind(wx.EVT_BUTTON, self.on_send_text)
        btns.Add(self.send_btn, flag=wx.RIGHT, border=6)
        self.live_btn = wx.Button(panel, label=_("Start live mode"))
        self.live_btn.Bind(wx.EVT_BUTTON, self.on_toggle_live)
        btns.Add(self.live_btn, flag=wx.RIGHT, border=6)
        self.stop_btn = wx.Button(panel, label=_("Stop (Shift+Escape)"))
        self.stop_btn.Bind(wx.EVT_BUTTON, lambda e: self.cancel())
        self.stop_btn.Enable(False)
        btns.Add(self.stop_btn, flag=wx.RIGHT, border=6)
        close_btn = wx.Button(panel, wx.ID_CLOSE, _("Close"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        btns.Add(close_btn)
        vbox.Add(btns, flag=wx.ALL, border=8)

        panel.SetSizer(vbox)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.talk_btn.SetFocus()

    # -- transcript / narration ------------------------------------------ #
    def _append(self, who, text):
        wx.CallAfter(self.transcript.AppendText, f"{who}: {text}\n")

    def _on_status(self, key):
        label = _STATUS_LABELS.get(key, key)
        wx.CallAfter(self.status.SetLabel, label)
        wx.CallAfter(_speak, label)

    def _on_transcript(self, text):
        self._append(_("You"), text)

    def _on_reply(self, text):
        # The reply is spoken by voice_io; here we only show it in the log.
        self._append(self.persona['name_en'], text)

    # -- confirmation (worker thread) ------------------------------------ #
    def _confirm(self, tool, args):
        result = {}
        done = threading.Event()

        def ask():
            try:
                argstr = ', '.join(f"{k}={v}" for k, v in (args or {}).items())
            except Exception:
                argstr = ''
            desc = f"{tool['name']}({argstr})"
            _speak(_("Confirm action: {action}").format(action=desc))
            dlg = wx.MessageDialog(
                self,
                _("The assistant wants to run:\n\n{action}\n\n{desc}\n\nAllow it?").format(
                    action=desc, desc=tool.get('description', '')),
                _("Confirm action"), wx.YES_NO | wx.ICON_QUESTION)
            result['ok'] = (dlg.ShowModal() == wx.ID_YES)
            dlg.Destroy()
            done.set()

        wx.CallAfter(ask)
        done.wait()
        return result.get('ok', False)

    # -- turn (voice or text) -------------------------------------------- #
    def on_talk(self, event):
        self._start_turn(goal_text=None)

    def on_send_text(self, event):
        text = self.input.GetValue().strip()
        if not text:
            return
        self.input.SetValue("")
        self._start_turn(goal_text=text)

    def _start_turn(self, goal_text):
        if self._running or self._live:
            return
        if not voice_assistant.is_available():
            wx.MessageBox(_("The assistant needs AI features enabled and a Gemini "
                            "API key (Settings, AI features)."),
                          _("AI not configured"), wx.OK | wx.ICON_WARNING, self)
            return
        self._running = True
        self._cancel = threading.Event()
        self.talk_btn.Enable(False)
        self.send_btn.Enable(False)
        self.live_btn.Enable(False)
        self.stop_btn.Enable(True)
        play_sound('core/SELECT.ogg')
        lang = get_setting('language', 'pl')

        def work():
            try:
                voice_assistant.run_turn(
                    self.persona, goal_text=goal_text,
                    on_status=self._on_status, on_transcript=self._on_transcript,
                    on_reply=self._on_reply, gui_confirm=self._confirm,
                    cancel_event=self._cancel, language=lang)
                wx.CallAfter(self._on_finished, None)
            except AgentCancelled:
                wx.CallAfter(self._on_finished, 'cancelled')
            except Exception as e:
                import traceback
                traceback.print_exc()
                wx.CallAfter(self._on_finished, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_finished(self, error):
        self._running = False
        self.talk_btn.Enable(True)
        self.send_btn.Enable(True)
        self.live_btn.Enable(True)
        self.stop_btn.Enable(False)
        if error == 'cancelled':
            self.status.SetLabel(_("Cancelled."))
            self._append(_("System"), _("Cancelled."))
            play_sound('core/error.ogg')
        elif error:
            self.status.SetLabel(_("Error."))
            self._append(_("System"), _("Error: {error}").format(error=error))
            _speak(_("Assistant error"))
            play_sound('core/error.ogg')
        else:
            self.status.SetLabel(_("Ready."))
        self.talk_btn.SetFocus()

    # -- live mode ------------------------------------------------------- #
    def on_toggle_live(self, event):
        if self._live:
            self.cancel()
            return
        if self._running:
            return
        if not voice_assistant.is_available():
            wx.MessageBox(_("The assistant needs AI features enabled and a Gemini "
                            "API key (Settings, AI features)."),
                          _("AI not configured"), wx.OK | wx.ICON_WARNING, self)
            return
        self._cancel = threading.Event()
        self.talk_btn.Enable(False)
        self.send_btn.Enable(False)
        self.stop_btn.Enable(True)
        self.live_btn.SetLabel(_("Stop live mode"))
        self._append(_("System"), _("Live mode started. Speak naturally."))

        def on_text(t):
            self._append(self.persona['name_en'], t)

        try:
            self._live = voice_assistant.run_live(
                self.persona, on_status=self._on_status, on_text=on_text,
                cancel_event=self._cancel)
        except Exception as e:
            self._live = None
            self._reset_live_buttons()
            wx.MessageBox(str(e), _("Live mode failed"), wx.OK | wx.ICON_ERROR, self)

    def _reset_live_buttons(self):
        self.talk_btn.Enable(True)
        self.send_btn.Enable(True)
        self.live_btn.Enable(True)
        self.stop_btn.Enable(False)
        self.live_btn.SetLabel(_("Start live mode"))

    # -- cancel / close -------------------------------------------------- #
    def cancel(self):
        if self._cancel is not None:
            self._cancel.set()
        if self._live:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None
            self._append(_("System"), _("Live mode stopped."))
            self._reset_live_buttons()
            self.status.SetLabel(_("Ready."))
        elif self._running:
            self.status.SetLabel(_("Cancelling..."))
            _speak(_("Cancelling"))

    def on_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            if event.ShiftDown():
                self.cancel()
                return
            if not self._running and not self._live:
                self.Close()
                return
        event.Skip()

    def on_close(self, event):
        self.cancel()
        event.Skip()


def open_assistant(parent, mode='turn'):
    """Entry point for the Program menu / global hotkey. ``mode`` may be 'turn'
    (default) or 'live' (auto-start a live session)."""
    if not ai_provider.is_ai_enabled():
        wx.MessageBox(_("Enable AI components in Settings, AI features first."),
                      _("AI features disabled"), wx.OK | wx.ICON_INFORMATION, parent)
        return
    persona = personas_mod.get_persona(ai_provider.get_assistant_model())
    if persona is None:
        wx.MessageBox(_("No assistant persona found in data/ai (Perun / Melitele)."),
                      _("Assistant unavailable"), wx.OK | wx.ICON_ERROR, parent)
        return
    frame = AssistantFrame(parent, persona)
    frame.Show()
    frame.Raise()
    if mode == 'live':
        wx.CallAfter(frame.on_toggle_live, None)
    return frame
