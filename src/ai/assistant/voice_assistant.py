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
SOUND_THINKING = 'ai/ui2.ogg'              # periodic "working" cue while thinking


class _ThinkingCue:
    """Plays a soft periodic cue between the end of dictation and the first spoken
    word, so the user gets audio feedback that the assistant is working instead of
    silence. ``stop()`` is idempotent and called the moment speech starts."""

    def __init__(self, interval=2.8):
        self._interval = interval
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        # First cue slightly delayed so a fast reply produces no cue at all.
        while not self._stop.wait(self._interval):
            try:
                play_sound(SOUND_THINKING)
            except Exception:
                pass

    def stop(self):
        self._stop.set()


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
        "weather, look up definitions of words and topics online, play music, "
        "and fully control Titan itself: read and change "
        "its settings, list and run its components and their actions, list and "
        "launch any Titan add-on (apps, games, IM modules and more), and use "
        "Titan IM - log in to Titan-Net or Telegram and send a private message "
        "to someone by name. Use your tools to actually do these things rather "
        "than only describing them. "
        "You can also BROWSE THE WEB in a real browser: open a page, read its "
        "text and its links, form fields, drop-downs and buttons, fill in forms "
        "field by field, choose options, click links and buttons, submit forms "
        "and go back. Prefer these browser tools when a task means visiting a "
        "website or filling in a form; read the page first so you know the exact "
        "field names and buttons. If the browser tools report that they are not "
        "available, open the page in the normal browser instead and use the "
        "screen-reading and clicking tools. "
        "PLANNING AND ASKING: when a request is complex, compound (several items "
        "or steps at once, e.g. 'order in Glovo 20 onions and 1 fries from shop "
        "X', or 'do this then that') or missing details (a "
        "reminder without a time, a message without its text or recipient, a "
        "form you have not been given the values for, booking or ordering "
        "something), do NOT guess and do NOT do half of it. Ask the user for the "
        "details you need by speaking a question and listening for the answer "
        "(the ask-the-user ability), ONE short question at a time, and keep "
        "asking until you have everything (for an order: the shop/restaurant, "
        "every item and quantity, the delivery address and payment if unknown); "
        "then read the plan back for confirmation before you place it, and only "
        "then carry the action out and confirm it is done. "
        "Speak in plain, natural language: NEVER say "
        "internal tool or function names (like run_shell or titan_send_message) "
        "or raw function-call syntax out loud - describe what you are doing in "
        "ordinary words. When you ask the user a question, put the WHOLE question "
        "in the question itself (it is spoken aloud); do not also repeat it as "
        "narration. Reply in the same language the user spoke. "
        "IMPORTANT for responsiveness: ALWAYS begin your reply with a very short "
        "spoken lead-in (a few words, e.g. 'Sure, one moment' / 'Jasne, chwila') "
        "BEFORE calling any tool, so the user hears you immediately instead of "
        "waiting in silence; then perform the action and give a short spoken "
        "confirmation when the task is done.")


def _confirm_from_policy(gui_confirm):
    """Return a confirm(tool, args)->bool honouring the AI Agent policy. Under
    'none' (Autonomous) everything auto-approves, including always-confirm tools;
    otherwise the GUI is asked. run_agent only invokes this for confirm-tier /
    always tools (and for every tool when confirm_all)."""
    policy = ai_provider.get_agent_confirm()

    def _confirm(tool, args):
        if policy == 'none':
            return True
        if gui_confirm is None:
            return True
        return gui_confirm(tool, args)
    return _confirm, (policy == 'all')


# --------------------------------------------------------------------------- #
# Turn (push-to-talk) mode
# --------------------------------------------------------------------------- #
def _titan_language():
    """Titan's currently configured UI language (falls back to 'pl')."""
    try:
        from src.settings.settings import get_setting
        return (get_setting('language', 'pl') or 'pl').split('_')[0]
    except Exception:
        return 'pl'


def run_turn(persona, *, goal_text=None, on_status=None, on_transcript=None,
             on_reply=None, gui_confirm=None, cancel_event=None,
             language=None, ask_user=None):
    """Run one assistant turn. If ``goal_text`` is None the user's speech is
    recorded and fed straight to the agent (Gemini is multimodal, so no separate
    speech-to-text round trip is on the critical path). Returns the final reply
    text ('' if nothing happened). Runs on the CALLING thread -- call it from a
    worker thread and marshal the callbacks to the GUI. Raises
    :class:`AgentCancelled` if the user cancels, or a clear RuntimeError on setup
    failure."""
    def status(msg):
        if on_status:
            on_status(msg)

    # Default to Titan's configured language, never a hardcoded 'pl'.
    language = language or _titan_language()

    if not ai_provider.get_ai_key(_ASSISTANT_PROVIDER):
        raise RuntimeError("The assistant needs a Gemini API key "
                           "(Settings, AI features).")

    # 1. Capture speech unless the caller supplied typed text.
    goal_audio = None
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
        # Feed the audio straight to the agent instead of transcribing first.
        # Transcription still runs, but in the BACKGROUND, only to show the
        # on-screen transcript and log the persona turn - it never delays speech.
        goal_audio = {'data': wav, 'mime_type': 'audio/wav'}
        goal_arg = ("The user's request is in the attached audio. Understand "
                    "what they said and carry it out.")

        def _bg_transcribe():
            try:
                txt = (voice_io.transcribe(wav, language_hint=language) or '').strip()
            except Exception as e:
                print(f"[assistant] background transcript failed: {e}")
                return
            if txt:
                if on_transcript:
                    on_transcript(txt)
                personas_mod.append_history(persona, 'user', txt)
        threading.Thread(target=_bg_transcribe, daemon=True).start()
    else:
        goal_text = (goal_text or '').strip()
        if not goal_text:
            status("nothing_heard")
            return ''
        if on_transcript:
            on_transcript(goal_text)
        personas_mod.append_history(persona, 'user', goal_text)
        goal_arg = goal_text

    # 2. Run the agent (computer-use + everyday tools) as this persona. Text is
    #    streamed to a sentence speaker so the assistant starts talking while the
    #    reply is still being generated (low latency), not only at the end.
    status("thinking")
    confirm, confirm_all = _confirm_from_policy(gui_confirm)
    system = build_system(persona)
    speaker = voice_io.SentenceSpeaker(persona=persona, cancel_event=cancel_event)
    thinking = _ThinkingCue().start()
    spoke_started = {'v': False}

    def _delta(chunk):
        if not spoke_started['v']:
            spoke_started['v'] = True
            thinking.stop()
            status("speaking")
        speaker.feed(chunk)

    # Interactive follow-up questions: unless the caller supplied its own way to
    # ask (e.g. a text dialog for a typed conversation), ask BY VOICE - say the
    # question in the persona's voice, then record and transcribe the answer. The
    # question is spoken only after any streamed lead-in has finished.
    def _voice_ask(question):
        thinking.stop()  # no "working" cue while we are asking/listening
        try:
            speaker.wait_idle()
        except Exception:
            pass
        if cancel_event is not None and cancel_event.is_set():
            raise AgentCancelled()
        voice_io.speak(question, persona=persona, cancel_event=cancel_event)
        play_sound(SOUND_INITIALIZED)
        status("listening")
        wav = voice_io.record_until_silence(cancel_event=cancel_event)
        play_sound(SOUND_DICTATION_END)
        if cancel_event is not None and cancel_event.is_set():
            raise AgentCancelled()
        status("thinking")
        if not wav:
            return None
        answer = (voice_io.transcribe(wav, language_hint=language) or '').strip()
        if answer and on_transcript:
            on_transcript(answer)
        return answer or None

    tools = get_assistant_tools(ask_user=(ask_user or _voice_ask))

    try:
        reply = run_agent(
            goal_arg, tools, provider=_ASSISTANT_PROVIDER, system=system,
            on_text=(on_reply if on_reply else None), on_text_delta=_delta,
            goal_audio=goal_audio,
            confirm=confirm, confirm_all=confirm_all, cancel_event=cancel_event)
    except BaseException:
        # Always tear the speaker down (cancel/errors included) so its worker
        # thread and audio stream never leak.
        speaker.finish(timeout=5)
        raise
    finally:
        thinking.stop()
    reply = (reply or '').strip()

    # 3. Flush the pipeline; if nothing was streamed/spoken (e.g. streaming
    #    unavailable), speak the whole reply once at the end.
    speaker.finish()
    if reply:
        personas_mod.append_history(persona, 'assistant', reply)
        if not speaker.spoke:
            status("speaking")
            voice_io.speak(reply, persona=persona, cancel_event=cancel_event)
    status("idle")
    return reply


# --------------------------------------------------------------------------- #
# Dictation mode (speech -> text typed into the focused field)
# --------------------------------------------------------------------------- #
def run_dictation(*, on_status=None, on_transcript=None, cancel_event=None,
                  language=None):
    """Record one utterance, transcribe it, and type the text at the current
    keyboard focus - no agent, no persona, no spoken reply. Used when an
    assistant hotkey is pressed while an editable text field is focused. Returns
    the typed text ('' if nothing was captured). Runs on the CALLING thread;
    raises :class:`AgentCancelled` if cancelled."""
    from .dictation import type_at_focus

    def status(msg):
        if on_status:
            on_status(msg)

    language = language or _titan_language()
    if not ai_provider.get_ai_key(_ASSISTANT_PROVIDER):
        raise RuntimeError("The assistant needs a Gemini API key "
                           "(Settings, AI features).")

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
    text = (voice_io.transcribe(wav, language_hint=language) or '').strip()
    if cancel_event is not None and cancel_event.is_set():
        raise AgentCancelled()
    if not text:
        status("nothing_heard")
        return ''

    # A trailing space so successive dictations don't run their words together.
    type_at_focus(text + ' ')
    if on_transcript:
        on_transcript(text)
    status("idle")
    return text


# --------------------------------------------------------------------------- #
# Live mode (Gemini Live API)
# --------------------------------------------------------------------------- #
class LiveSession:
    """A real-time spoken conversation with the persona via the Gemini Live API.

    Streams microphone audio up and plays the model's audio down continuously,
    on a background asyncio loop. ``stop()`` (or the shared ``cancel_event``)
    ends it. Requires ``sounddevice`` and the ``google-genai`` Live API.
    """

    # Newest native-audio model first = lowest latency to first sound; each is
    # tried in order and we fall back to the next if it is unavailable for this
    # key. Live model IDs are a moving target - refresh from
    # https://ai.google.dev/gemini-api/docs/live-api/capabilities when they 404.
    LIVE_MODELS = (
        'gemini-3.1-flash-live-preview',              # current recommended (native audio)
        'gemini-2.5-flash-native-audio-preview-12-2025',
        'gemini-2.0-flash-live-001',                  # older half-cascade fallback
    )
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
        from google import genai

        key = ai_provider.get_ai_key(_ASSISTANT_PROVIDER)
        if not key:
            self._status("error: no Gemini key")
            return
        client = genai.Client(api_key=key)

        # Try each candidate model in order. Only fall through to the next one on
        # a connection-establishment failure (e.g. the preview model is not
        # available for this key) - never after we were genuinely live.
        last_err = None
        for model_name in self.LIVE_MODELS:
            connected = {'v': False}
            try:
                await self._session_with(client, model_name, connected)
                return  # clean end (user stopped)
            except Exception as e:
                last_err = e
                if self.cancel_event.is_set() or connected['v']:
                    break
                print(f"[assistant] live model {model_name} unavailable "
                      f"({e}); trying fallback.")
        if last_err and not self.cancel_event.is_set():
            traceback.print_exc()
            self._status(f"error: {last_err}")

    async def _session_with(self, client, model_name, connected):
        import asyncio
        import sounddevice as sd
        import numpy as np
        from google.genai import types

        voice = (self.persona or {}).get('gemini_voice') or 'Kore'
        config = types.LiveConnectConfig(
            response_modalities=['AUDIO'],
            system_instruction=build_system(self.persona),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice))))

        loop = asyncio.get_event_loop()
        # 'low' latency keeps the playback buffer small -> less delay to first word.
        out_stream = sd.OutputStream(samplerate=self.OUT_SR, channels=1,
                                     dtype='int16', latency='low')
        out_stream.start()

        try:
            async with client.aio.live.connect(model=model_name,
                                                config=config) as session:
                connected['v'] = True
                play_sound(SOUND_INITIALIZED)
                self._status("live")

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
