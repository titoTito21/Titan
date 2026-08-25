"""
The session host's Titan TTS, narrating an interactive game.

The AI used to speak for itself: Gemini was asked for AUDIO and shipped
its own voice to every player. That meant nothing was heard until the
model had finished both writing and speaking a sentence, a player who
wanted to cut in had to wait out a stream already in flight, and the
narrator was whatever voice the model happened to be configured with.

Now the model is asked for TEXT and the **host speaks it**. The server
sends this machine a ``game_speak_request``; Titan renders it with
whatever engine and voice the user actually has (Supertonic, Eloquence,
SAPI, DECtalk, ElevenLabs, ...), streams the audio back as
``game_speech_chunk``, and the server relays it to the table as the
``game_ai_audio`` every client already plays. One narrator for the whole
table, chosen by the person running the game.

Three things make it feel immediate, which is the whole point:

* **It is rendered a sentence at a time.** The first sentence is on its
  way while the rest is still being synthesised, so narration starts in
  the time it takes to say one sentence rather than one paragraph.
* **It is raw PCM**, at the rate the engine produced, which is the path
  the clients already play gaplessly through sounddevice - so sentence
  after sentence sounds like one voice reading, not like clips.
* **An interruption is instant.** Cancelling means stopping a local
  synthesis loop and not sending the rest, so nothing already in flight
  has to be waited out.

Synthesis happens on a worker thread of its own. It must not touch the
GUI thread: an engine is a subprocess, a DLL or an HTTP call, and a
second of it on the GUI thread is a second of a frozen Titan.
"""

import base64
import queue
import re
import threading
from typing import Callable, Dict, List, Optional

try:
    from src.titan_core import stereo_speech
except Exception:  # pragma: no cover - Titan not importable (tests, tooling)
    stereo_speech = None


# A chunk is one sentence, so this is only a ceiling for a "sentence"
# that is really a wall of text with no full stop in it.
MAX_SENTENCE_CHARS = 400

# The server refuses anything larger, and a sentence never approaches it.
MAX_CHUNK_B64 = 512 * 1024

# More than this queued means the model is talking faster than anyone can
# listen; the extra is dropped rather than played minutes late.
MAX_QUEUED = 8


def split_sentences(text: str) -> List[str]:
    """Break narration into the units it will be spoken in.

    Sentence-sized, because that is the smallest piece that still sounds
    like speech rather than like a clip - and the largest piece that can
    be sent before the rest has been synthesised. A "sentence" longer
    than MAX_SENTENCE_CHARS is split on whitespace so one runaway
    paragraph cannot hold the whole line back.
    """
    text = (text or '').strip()
    if not text:
        return []
    parts: List[str] = []
    for raw in re.split(r'(?<=[.!?…])\s+|\n+', text):
        piece = raw.strip()
        if not piece:
            continue
        while len(piece) > MAX_SENTENCE_CHARS:
            cut = piece.rfind(' ', 0, MAX_SENTENCE_CHARS)
            if cut <= 0:
                cut = MAX_SENTENCE_CHARS
            parts.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if piece:
            parts.append(piece)
    return parts


class GameNarrator:
    """Renders the AI's lines with this machine's Titan TTS and streams
    them to the server.

    ``send`` is handed one dict per message and is expected to put it on
    the wire; nothing here knows about websockets. It is called from the
    worker thread, so a caller that needs the GUI thread must marshal.
    """

    def __init__(self, send: Callable[[Dict], None], session_id: int):
        self._send = send
        self.session_id = int(session_id)
        self._queue: "queue.Queue[Optional[Dict]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        # The utterance being rendered right now. An interrupt clears it,
        # and the loop checks it between sentences - which is why cutting
        # in costs at most one sentence rather than a whole paragraph.
        self._current: Optional[str] = None
        self._cancelled = set()
        self._lock = threading.Lock()

    # ---------------- capability ----------------

    @staticmethod
    def speech():
        """Titan's live speech object, or None."""
        if stereo_speech is None:
            return None
        try:
            return stereo_speech.get_stereo_speech()
        except Exception:
            return None

    @classmethod
    def can_narrate(cls) -> bool:
        """Whether this machine can narrate for a table at all.

        It is the same question ``speak_concat`` asks - can the ACTIVE
        engine render an utterance to memory - because an engine that can
        only play out of its own speakers can play to this user and
        nobody else.
        """
        speech = cls.speech()
        if speech is None:
            return False
        try:
            return bool(speech.supports_segment_synthesis())
        except Exception:
            return False

    @classmethod
    def voice_name(cls) -> Optional[str]:
        """What to tell the table it is being narrated by."""
        speech = cls.speech()
        if speech is None:
            return None
        try:
            engine = getattr(speech, 'engine', '') or ''
            voice = getattr(speech, 'voice_name', '') or getattr(speech, 'voice', '') or ''
            return (engine + (' / ' + str(voice) if voice else '')) or None
        except Exception:
            return None

    # ---------------- life cycle ----------------

    def start(self):
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name='TitanGameNarrator', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    # ---------------- what the server asks for ----------------

    def request(self, message: Dict):
        """A ``game_speak_request``. Queued, never rendered here: this is
        called from the websocket's own thread."""
        uid = str(message.get('utterance_id') or '')
        if not uid:
            return
        if message.get('interrupt'):
            self.cancel_all()
        if self._queue.qsize() >= MAX_QUEUED:
            # Further behind than anybody could listen. Refusing tells the
            # server to have the table speak this one, which is heard now
            # rather than in a minute.
            self._fail(uid, 'narrator is too far behind')
            return
        self.start()
        self._queue.put(dict(message))

    def cancel_all(self):
        """Stop narrating. Everything queued is dropped and the sentence
        being rendered is the last one that will be sent."""
        with self._lock:
            if self._current:
                self._cancelled.add(self._current)
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                continue
            with self._lock:
                self._cancelled.add(str(item.get('utterance_id') or ''))

    # ---------------- the worker ----------------

    def _run(self):
        while not self._stop.is_set():
            try:
                message = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if message is None:
                break
            try:
                self._render(message)
            except Exception as e:
                uid = str(message.get('utterance_id') or '')
                print(f"[Game Narrator] {uid}: {e}")
                self._fail(uid, str(e))

    def _render(self, message: Dict):
        uid = str(message.get('utterance_id') or '')
        text = (message.get('text') or '').strip()
        if not uid or not text:
            return
        speech = self.speech()
        if speech is None:
            self._fail(uid, 'no speech engine')
            return

        with self._lock:
            self._current = uid
            self._cancelled.discard(uid)

        sentences = split_sentences(text)
        if not sentences:
            self._fail(uid, 'nothing to say')
            return

        sent_any = False
        try:
            for index, sentence in enumerate(sentences):
                if self._is_cancelled(uid) or self._stop.is_set():
                    # Cut short on purpose: somebody interrupted, and the
                    # rest of this line is no longer what the table is
                    # listening for. What was already sent stands.
                    break
                pcm, rate = self._synthesize(speech, sentence)
                if pcm is None:
                    if sent_any:
                        # Part of the line is already being heard, so
                        # handing the WHOLE line to the table's own voices
                        # would say the beginning of it twice.
                        continue
                    self._fail(uid, 'engine could not render')
                    return
                if self._is_cancelled(uid):
                    break
                audio_b64 = base64.b64encode(pcm).decode('ascii')
                if len(audio_b64) > MAX_CHUNK_B64:
                    continue
                self._send({
                    'type': 'game_speech_chunk',
                    'session_id': self.session_id,
                    'utterance_id': uid,
                    'audio_b64': audio_b64,
                    # The rate travels with the audio: the players' side
                    # re-opens its stream when it changes, so an engine
                    # that renders at 22050 is not played at 24000 and a
                    # semitone sharp.
                    'mime_type': 'audio/pcm;rate=%d' % rate,
                    'seq': index,
                    'final': False,
                })
                sent_any = True
        finally:
            with self._lock:
                if self._current == uid:
                    self._current = None
                self._cancelled.discard(uid)

        if sent_any:
            # Closes the utterance server-side so its deadline stops
            # running; an unclosed one would be handed to the table.
            self._send({
                'type': 'game_speech_chunk',
                'session_id': self.session_id,
                'utterance_id': uid,
                'final': True,
            })
        elif not self._stop.is_set():
            self._fail(uid, 'interrupted before anything was said')

    @staticmethod
    def _synthesize(speech, sentence: str):
        """One sentence as mono 16-bit PCM, and the rate it is at.

        Mono int16 because that is what the players' streaming path
        opens; handing it anything else is a stream that plays at the
        wrong speed rather than one that refuses.
        """
        try:
            audio = speech._synthesize_segment(sentence)
        except Exception as e:
            print(f"[Game Narrator] synthesis failed: {e}")
            return None, 0
        if audio is None:
            return None, 0
        try:
            audio = audio.set_channels(1).set_sample_width(2)
            return audio.raw_data, int(audio.frame_rate)
        except Exception as e:
            print(f"[Game Narrator] could not convert audio: {e}")
            return None, 0

    def _is_cancelled(self, uid: str) -> bool:
        with self._lock:
            return uid in self._cancelled

    def _fail(self, uid: str, reason: str):
        """Tell the server this line was not spoken, so the table says it
        with its own voices instead of waiting out the deadline."""
        if not uid:
            return
        try:
            self._send({
                'type': 'game_speech_failed',
                'session_id': self.session_id,
                'utterance_id': uid,
                'error': reason[:200],
            })
        except Exception as e:
            print(f"[Game Narrator] could not report failure: {e}")
