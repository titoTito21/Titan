"""Windowless (speech-only) voice assistant, launched by the global / Titan-UI
hotkeys.

Pressing an assistant hotkey should just start *talking* to the assistant - no
window, no visual UI. This module runs a single push-to-talk turn entirely by
ear:

* an audible cue marks that it is listening (``ai/initialized.ogg``) and that
  dictation ended (``ai/ui1.ogg``) - both come from :func:`voice_assistant.run_turn`;
* status is narrated to the screen reader (Listening / Thinking / Speaking / ...);
* the persona speaks its reply in its Gemini voice;
* risky agent actions still raise a confirmation dialog (parented to the main
  frame) exactly as the windowed assistant does;
* **Shift+Escape** cancels the run, and pressing the SAME hotkey again while a
  turn is in progress also stops it (a natural toggle).

The windowed assistant (Program menu) is unchanged; only the hotkeys use this.
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
except Exception:  # pragma: no cover - sound is optional
    def play_sound(*_a, **_k):
        pass


def _speak(text):
    """Narrate ``text`` (Titan TTS when enabled, else screen reader / notification
    voice; best effort, never raises)."""
    from src.ai.ai_speech import speak
    speak(text)


# Spoken status announcements (no window to show them in).
_STATUS_LABELS = {
    'listening': _("Listening..."),
    'nothing_heard': _("I did not hear anything."),
    'transcribing': _("Transcribing..."),
    'thinking': _("Thinking..."),
    'speaking': _("Speaking..."),
    'idle': _("Ready."),
}


class _HeadlessAssistant:
    """Singleton that owns at most one in-flight windowless turn."""

    def __init__(self):
        self._running = False
        self._cancel = None
        self._parent = None
        self._shift_esc_handle = None
        self._lock = threading.Lock()

    # -- public entry ---------------------------------------------------- #
    def launch(self, parent):
        """Start a windowless push-to-talk turn. If one is already running,
        this stops it instead (press-again-to-cancel)."""
        with self._lock:
            if self._running:
                # Second press: toggle off.
                self.cancel()
                return
            if not voice_assistant.is_available():
                _speak(_("The assistant needs AI features enabled and a Gemini "
                         "API key (Settings, AI features)."))
                return
            persona = personas_mod.get_persona(ai_provider.get_assistant_model())
            if persona is None:
                _speak(_("No assistant persona found in data/ai (Perun / "
                         "Melitele)."))
                return
            self._parent = parent
            self._running = True
            self._cancel = threading.Event()

        # If the user is sitting in an editable text field, a hotkey press means
        # "dictate into this field", not "run a command". Detect that HERE (on the
        # GUI thread, while the field still holds focus) before anything records.
        dictate = False
        try:
            if ai_provider.get_assistant_dictation():
                from src.ai.assistant import dictation
                dictate = dictation.focused_editable()
        except Exception as e:
            print(f"[assistant.headless] focus check failed: {e}")

        self._register_shift_esc()
        lang = get_setting('language', 'pl')

        def work():
            try:
                if dictate:
                    _speak(_("Dictation"))
                    voice_assistant.run_dictation(
                        on_status=self._on_status, on_transcript=None,
                        cancel_event=self._cancel, language=lang)
                else:
                    voice_assistant.run_turn(
                        persona, goal_text=None,
                        on_status=self._on_status, on_transcript=None,
                        on_reply=None, gui_confirm=self._confirm,
                        cancel_event=self._cancel, language=lang)
                wx.CallAfter(self._finish, None)
            except AgentCancelled:
                wx.CallAfter(self._finish, 'cancelled')
            except Exception as e:
                import traceback
                traceback.print_exc()
                wx.CallAfter(self._finish, str(e))

        threading.Thread(target=work, daemon=True).start()

    def cancel(self):
        if self._cancel is not None:
            self._cancel.set()
            _speak(_("Cancelling"))

    # -- callbacks ------------------------------------------------------- #
    def _on_status(self, key):
        label = _STATUS_LABELS.get(key, key)
        wx.CallAfter(_speak, label)

    def _confirm(self, tool, args):
        """Ask the user to allow a risky agent action (worker thread -> GUI)."""
        result = {}
        done = threading.Event()

        def ask():
            from src.ai.agent_tools import describe_action
            desc = (describe_action(tool['name'], args)
                    or tool.get('description') or tool['name'])
            _speak(_("Confirm action: {action}").format(action=desc))
            dlg = wx.MessageDialog(
                self._parent,
                _("The assistant wants to run:\n\n{action}\n\n{desc}\n\n"
                  "Allow it?").format(action=desc,
                                      desc=tool.get('description', '')),
                _("Confirm action"), wx.YES_NO | wx.ICON_QUESTION)
            result['ok'] = (dlg.ShowModal() == wx.ID_YES)
            dlg.Destroy()
            done.set()

        wx.CallAfter(ask)
        done.wait()
        return result.get('ok', False)

    def _finish(self, error):
        self._unregister_shift_esc()
        with self._lock:
            self._running = False
            self._cancel = None
        if error == 'cancelled':
            play_sound('core/error.ogg')
            _speak(_("Cancelled."))
        elif error:
            play_sound('core/error.ogg')
            _speak(_("Assistant error"))

    # -- Shift+Escape global cancel (only while a turn runs) ------------- #
    def _register_shift_esc(self):
        try:
            import keyboard
        except Exception:
            return
        try:
            self._shift_esc_handle = keyboard.add_hotkey(
                'shift+esc', lambda: wx.CallAfter(self.cancel), suppress=False)
        except Exception:
            self._shift_esc_handle = None

    def _unregister_shift_esc(self):
        if self._shift_esc_handle is None:
            return
        try:
            import keyboard
            keyboard.remove_hotkey(self._shift_esc_handle)
        except Exception:
            pass
        self._shift_esc_handle = None


_instance = _HeadlessAssistant()


def launch(parent=None):
    """Start (or toggle off) a windowless speech assistant turn."""
    _instance.launch(parent)
