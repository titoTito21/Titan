"""Accessible conversation view for the Titan AI Agent.

The user types a goal; the agent (see :mod:`src.ai.ai_agent`) operates the
computer to achieve it. Everything the agent says and does is appended to a
screen-reader-friendly transcript AND spoken via Titan TTS / accessible_output3,
so a blind user can follow along. Risky actions are confirmed according to the
policy in Settings, AI features. Shift+Escape cancels a running agent at once.
"""

import threading

import wx

from src.ai import ai_provider, ai_agent, agent_tools
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


class AIAgentFrame(wx.Frame):
    def __init__(self, parent):
        super().__init__(parent, title=_("Titan AI Agent"), size=(720, 620))
        self._cancel = None          # threading.Event for the active run
        self._running = False

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

        vbox.Add(wx.StaticText(panel, label=_("Your instruction:")),
                 flag=wx.LEFT | wx.TOP, border=8)
        self.input = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER,
                                 size=(-1, 70))
        self.input.SetName(_("Your instruction"))
        self.input.Bind(wx.EVT_TEXT_ENTER, self.on_send)
        vbox.Add(self.input, flag=wx.EXPAND | wx.LEFT | wx.RIGHT, border=8)

        btns = wx.BoxSizer(wx.HORIZONTAL)
        self.send_btn = wx.Button(panel, label=_("Send"))
        self.send_btn.Bind(wx.EVT_BUTTON, self.on_send)
        btns.Add(self.send_btn, flag=wx.RIGHT, border=6)
        self.stop_btn = wx.Button(panel, label=_("Stop (Shift+Escape)"))
        self.stop_btn.Bind(wx.EVT_BUTTON, lambda e: self.cancel_agent())
        self.stop_btn.Enable(False)
        btns.Add(self.stop_btn, flag=wx.RIGHT, border=6)
        close_btn = wx.Button(panel, wx.ID_CLOSE, _("Close"))
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())
        btns.Add(close_btn)
        vbox.Add(btns, flag=wx.ALL, border=8)

        panel.SetSizer(vbox)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.input.SetFocus()

    # -- transcript / narration ------------------------------------------ #
    def _append(self, who, text):
        self.transcript.AppendText(f"{who}: {text}\n")

    def _on_text(self, text):
        wx.CallAfter(self.__on_text, text)

    def __on_text(self, text):
        self._append(_("Agent"), text)
        _speak(text)

    def _on_tool_start(self, name, args):
        wx.CallAfter(self.__on_tool_start, name, args)

    def __on_tool_start(self, name, args):
        desc = self._describe_action(name, args)
        self._append(_("Action"), desc)
        self.status.SetLabel(desc)
        _speak(desc)

    def _on_tool_result(self, name, result):
        wx.CallAfter(self.__on_tool_result, name, result)

    def __on_tool_result(self, name, result):
        short = (result or '').strip().replace('\n', ' ')
        if len(short) > 300:
            short = short[:300] + '...'
        self._append(_("Result"), short)

    def _describe_action(self, name, args):
        try:
            argstr = ', '.join(f"{k}={v}" for k, v in (args or {}).items())
        except Exception:
            argstr = ''
        return f"{name}({argstr})" if argstr else f"{name}()"

    # -- confirmation (called on the worker thread) ---------------------- #
    def _confirm(self, tool, args):
        policy = ai_provider.get_agent_confirm()
        if policy == 'none' and not tool.get('always_confirm'):
            return True
        result = {}
        done = threading.Event()

        def ask():
            desc = self._describe_action(tool['name'], args)
            msg = _("The agent wants to run this action:\n\n{action}\n\n{desc}\n\nAllow it?").format(
                action=desc, desc=tool.get('description', ''))
            _speak(_("Confirm action: {action}").format(action=desc))
            dlg = wx.MessageDialog(self, msg, _("Confirm agent action"),
                                   wx.YES_NO | wx.ICON_QUESTION)
            result['ok'] = (dlg.ShowModal() == wx.ID_YES)
            dlg.Destroy()
            done.set()

        wx.CallAfter(ask)
        done.wait()
        return result.get('ok', False)

    # -- run / cancel ---------------------------------------------------- #
    def on_send(self, event):
        if self._running:
            return
        goal = self.input.GetValue().strip()
        if not goal:
            return
        if not ai_provider.is_ai_ready():
            wx.MessageBox(_("AI features are not configured. Enable them and set "
                            "a method in Settings, AI features."),
                          _("AI not configured"), wx.OK | wx.ICON_WARNING, self)
            return
        self.input.SetValue("")
        self._append(_("You"), goal)
        self._running = True
        self._cancel = threading.Event()
        self.send_btn.Enable(False)
        self.stop_btn.Enable(True)
        self.status.SetLabel(_("Working..."))
        _speak(_("Agent working"))
        play_sound('core/SELECT.ogg')

        policy = ai_provider.get_agent_confirm()
        tools = agent_tools.get_tools()

        def work():
            try:
                final = ai_agent.run_agent(
                    goal, tools,
                    on_text=self._on_text,
                    on_tool_start=self._on_tool_start,
                    on_tool_result=self._on_tool_result,
                    confirm=self._confirm,
                    confirm_all=(policy == 'all'),
                    cancel_event=self._cancel)
                wx.CallAfter(self._on_finished, final, None)
            except ai_agent.AgentCancelled:
                wx.CallAfter(self._on_finished, None, 'cancelled')
            except Exception as e:
                import traceback
                traceback.print_exc()
                wx.CallAfter(self._on_finished, None, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_finished(self, final, error):
        self._running = False
        self.send_btn.Enable(True)
        self.stop_btn.Enable(False)
        if error == 'cancelled':
            self.status.SetLabel(_("Cancelled."))
            self._append(_("System"), _("Agent cancelled."))
            play_sound('core/error.ogg')
        elif error:
            self.status.SetLabel(_("Error."))
            self._append(_("System"), _("Error: {error}").format(error=error))
            _speak(_("Agent error"))
            play_sound('core/error.ogg')
        else:
            self.status.SetLabel(_("Done."))
            _speak(_("Agent finished"))
            play_sound('core/SELECT.ogg')
        self.input.SetFocus()

    def cancel_agent(self):
        if self._running and self._cancel is not None:
            self._cancel.set()
            self.status.SetLabel(_("Cancelling..."))
            _speak(_("Cancelling agent"))

    def on_char_hook(self, event):
        # Shift+Escape cancels a running agent; plain Escape closes when idle.
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            if event.ShiftDown():
                self.cancel_agent()
                return
            if not self._running:
                self.Close()
                return
        event.Skip()

    def on_close(self, event):
        self.cancel_agent()
        event.Skip()


def open_agent(parent):
    """Entry point for the Program menu."""
    if not ai_provider.is_ai_enabled():
        wx.MessageBox(_("Enable AI components in Settings, AI features first."),
                      _("AI features disabled"), wx.OK | wx.ICON_INFORMATION, parent)
        return
    frame = AIAgentFrame(parent)
    frame.Show()
    frame.Raise()
