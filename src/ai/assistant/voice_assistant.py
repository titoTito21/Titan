"""Voice-assistant orchestration for Perun / Melitele.

Two modes:

* **Turn mode** (:func:`run_turn`) - push-to-talk: record one utterance ->
  transcribe (cloud) -> run the computer-use + everyday-tools agent -> speak the
  reply with the persona's Gemini voice. The agentic actions honour the AI Agent
  confirmation policy and are cancellable with Shift+Escape (``cancel_event``),
  exactly like the standalone agent.

* **Live mode** (:func:`run_live`) - a continuous, real-time spoken conversation
  using the Gemini Live API (like Gemini / ChatGPT voice), interruptible via the
  same cancel event.

The assistant always uses the Gemini provider (its voice + speech recognition
are Gemini features), regardless of the provider chosen for other AI features.
"""

import threading
import traceback

from src.ai import ai_provider
from src.ai.ai_agent import run_agent, AgentCancelled
from src.ai.assistant import personas as personas_mod
from src.ai.assistant import voice_io
from src.ai.assistant.assistant_tools import get_assistant_tools

try:
    from src.titan_core.sound import play_sound
except Exception:  # pragma: no cover
    def play_sound(*_a, **_k):
        pass

_ASSISTANT_PROVIDER = 'gemini'

SOUND_INITIALIZED = 'ai/initialized.ogg'   # assistant launched / listening
SOUND_DICTATION_END = 'ai/ui1.ogg'         # end of dictation


def is_available():
    """True if the assistant can run: AI enabled and a Gemini key is present."""
    return ai_provider.is_ai_enabled() and bool(ai_provider.get_ai_key(_ASSISTANT_PROVIDER))


def build_system(persona):
    """The persona's character prompt plus assistant operating guidance."""
    base = (persona or {}).get('system_instruction', '') or (
        "You are a helpful voice assistant for the Titan (TCE) desktop.")
    return (
        base + "\n\n"
        "You are a spoken voice assistant. Keep replies concise and natural for "
        "speech. You can control the computer, search the web, check the "
        "weather, play music, and launch Titan apps and games by name - use "
        "your tools to actually do these things rather than only describing "
        "them. Reply in the same language the user spoke. When a task is done, "
        "give a short spoken confirmation.")


def _confirm_from_policy(gui_confirm):
    """Return a confirm(tool, args)->bool honouring the AI Agent policy. Under
    'none' everything auto-approves except tools marked always_confirm; otherwise
    the GUI is asked. run_agent only invokes this for confirm-tier / always tools
    (and for every tool when confirm_all)."""
    policy = ai_provider.get_agent_confirm()

    def _confirm(tool, args):
        if policy == 'none' and not tool.get('always_confirm'):
            return True
        if gui_confirm is None:
            return True
        return gui_confirm(tool, args)
    return _confirm, (policy == 'all')


# --------------------------------------------------------------------------- #
# Turn (push-to-talk) mode
# --------------------------------------------------------------------------- #
def run_turn(persona, *, goal_text=None, on_status=None, on_transcript=None,
             on_reply=None, gui_confirm=None, cancel_event=None,
             language='pl'):
    """Run one assistant turn. If ``goal_text`` is None the user's speech is
    recorded and transcribed first. Returns the final reply text ('' if nothing
    happened). Runs on the CALLING thread -- call it from a worker thread and
    marshal the callbacks to the GUI. Raises :class:`AgentCancelled` if the user
    cancels, or a clear RuntimeError on setup failure."""
    def status(msg):
        if on_status:
            on_status(msg)

    if not ai_provider.get_ai_key(_ASSISTANT_PROVIDER):
        raise RuntimeError("The assistant needs a Gemini API key "
                           "(Settings, AI features).")

    # 1. Capture speech unless the caller supplied typed text.
    if goal_text is None:
        play_sound(SOUND_INITIALIZED)
        status("listening")
        wav = voice_io.record_until_silence(cancel_event=cancel_event)
        play_sound(SOUND_DICTATION_END)
        if cancel_event is not None and cancel_event.is_set():
            raise AgentCancelled()
        if not wav:
            status("nothing_heard")
            return ''
        status("transcribing")
        goal_text = voice_io.transcribe(wav, language_hint=language)
    goal_text = (goal_text or '').strip()
    if not goal_text:
        status("nothing_heard")
        return ''
    if on_transcript:
        on_transcript(goal_text)
    personas_mod.append_history(persona, 'user', goal_text)

    # 2. Run the agent (computer-use + everyday tools) as this persona.
    status("thinking")
    confirm, confirm_all = _confirm_from_policy(gui_confirm)
    tools = get_assistant_tools()
    system = build_system(persona)

    reply = run_agent(
        goal_text, tools, provider=_ASSISTANT_PROVIDER, system=system,
        on_text=(on_reply if on_reply else None),
        confirm=confirm, confirm_all=confirm_all, cancel_event=cancel_event)
    reply = (reply or '').strip()

    # 3. Speak the reply.
    if reply:
        personas_mod.append_history(persona, 'assistant', reply)
        status("speaking")
        voice_io.speak(reply, persona=persona, cancel_event=cancel_event)
    status("idle")
    return reply


# --------------------------------------------------------------------------- #
# Live mode (Gemini Live API)
# --------------------------------------------------------------------------- #
class LiveSession:
    """A real-time spoken conversation with the persona via the Gemini Live API.

    Streams microphone audio up and plays the model's audio down continuously,
    on a background asyncio loop. ``stop()`` (or the shared ``cancel_event``)
    ends it. Requires ``sounddevice`` and the ``google-genai`` Live API.
    """

    LIVE_MODEL = 'gemini-2.0-flash-live-001'
    IN_SR = 16000
    OUT_SR = 24000

    def __init__(self, persona, *, on_status=None, on_text=None,
                 cancel_event=None):
        self.persona = persona
        self.on_status = on_status
        self.on_text = on_text
        self.cancel_event = cancel_event or threading.Event()
        self._thread = None

    def _status(self, msg):
        if self.on_status:
            try:
                self.on_status(msg)
            except Exception:
                pass

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.cancel_event.set()

    def _run(self):
        try:
            import asyncio
            asyncio.run(self._session())
        except Exception as e:
            traceback.print_exc()
            self._status(f"error: {e}")

    async def _session(self):
        import asyncio
        import sounddevice as sd
        import numpy as np
        from google import genai
        from google.genai import types

        key = ai_provider.get_ai_key(_ASSISTANT_PROVIDER)
        if not key:
            self._status("error: no Gemini key")
            return
        client = genai.Client(api_key=key)
        voice = (self.persona or {}).get('gemini_voice') or 'Kore'
        config = types.LiveConnectConfig(
            response_modalities=['AUDIO'],
            system_instruction=build_system(self.persona),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice))))

        play_sound(SOUND_INITIALIZED)
        self._status("live")
        loop = asyncio.get_event_loop()
        out_stream = sd.OutputStream(samplerate=self.OUT_SR, channels=1,
                                     dtype='int16')
        out_stream.start()

        try:
            async with client.aio.live.connect(model=self.LIVE_MODEL,
                                                config=config) as session:
                async def _send_mic():
                    mic_q = asyncio.Queue()

                    def _cb(indata, _frames, _t, _status):
                        try:
                            loop.call_soon_threadsafe(
                                mic_q.put_nowait, bytes(indata))
                        except Exception:
                            pass
                    with sd.RawInputStream(samplerate=self.IN_SR, channels=1,
                                           dtype='int16', blocksize=1600,
                                           callback=_cb):
                        while not self.cancel_event.is_set():
                            chunk = await mic_q.get()
                            await session.send_realtime_input(
                                audio=types.Blob(data=chunk,
                                                 mime_type='audio/pcm;rate=16000'))

                async def _recv():
                    while not self.cancel_event.is_set():
                        async for response in session.receive():
                            if self.cancel_event.is_set():
                                break
                            data = getattr(response, 'data', None)
                            if data:
                                arr = np.frombuffer(data, dtype=np.int16)
                                out_stream.write(arr)
                            text = getattr(response, 'text', None)
                            if text and self.on_text:
                                self.on_text(text)

                sender = asyncio.create_task(_send_mic())
                receiver = asyncio.create_task(_recv())
                while not self.cancel_event.is_set():
                    await asyncio.sleep(0.1)
                sender.cancel()
                receiver.cancel()
        finally:
            try:
                out_stream.stop()
                out_stream.close()
            except Exception:
                pass
            self._status("idle")


def run_live(persona, **kwargs):
    """Start a live session and return it (call ``.stop()`` to end)."""
    session = LiveSession(persona, **kwargs)
    session.start()
    return session
