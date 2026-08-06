# -*- coding: utf-8 -*-
"""Speech output for Titan Access.

Python port of the C# ``ScreenReader.SpeechManager``. Instead of re-implementing
SAPI5 / OneCore / BestSpeech and the bespoke NAudio stereo capture, this adapter
delegates to **Titan's own configured TTS engine** (:mod:`src.titan_core.tce_speech`),
which already provides:

* a configurable synthesizer (eSpeak / SAPI5 / ElevenLabs / ...),
* true stereo positioning (``position`` -1.0 left .. 1.0 right), and
* additive pitch control (``pitch_offset`` -10 .. 10),

mirroring exactly what ``SpeechManager.SpeakStereo`` did by hand. The reader
speaks ONLY through Titan TTS -- the engine is forced on (via
``tce_speech.ensure_titan_engine``) even when Titan's "stereo speech" setting is
disabled, because that setting only governs stereo positioning, not which engine
speaks. Titan Access NEVER speaks through ``accessible_output3``; if Titan TTS is
genuinely unavailable (e.g. running the reader standalone) it degrades straight
to a plain ``print`` so the screen reader never hard-crashes.

``supports_pitch`` reports whether the active path honours ``pitch_offset``. The
orchestrator uses it to decide between the three-part pitched announcement
(name / type / state, like Titan Talk) and a single flat line.

This module emits no user-facing text, so it needs no localization keys.
"""

import threading
import time

from titan_access.contracts import SpeechLike  # noqa: F401  (documents intent)


# Map the screen-reader ``Synthesizer`` setting (PascalCase, from the C# dialog)
# to a Titan TTS engine id where a sensible equivalent exists. Anything else is
# passed through lower-cased; the Titan engine simply ignores unknown ids.
# NOTE: "bestspeech" is deliberately NOT aliased here -- it is itself a real,
# first-class TitanTTS engine id (data/titantts engines/bestspeech/__engine__.py),
# so it must pass through unchanged. An earlier version of this table predated
# that plugin and aliased it to "espeak", which silently hijacked every
# set_engine("bestspeech") call (e.g. from the dial's engine-cycle gesture).
_SYNTH_TO_ENGINE = {
    "sapi5": "sapi5",
    "onecore": "sapi5",       # nearest Windows-native equivalent
}


def _estimate_duration(text, cap=2.5):
    """Rough spoken duration (seconds) used to pace speech.

    Matches the heuristic in ``titan_talk.tt_core`` so pacing feels the same
    across the suite when the engine cannot report :attr:`is_speaking`. Pass
    ``cap=None`` when the estimate has to cover a whole utterance (the queue
    pump): capping it at 2.5 s would start the next one over a long sentence.
    """
    seconds = 0.28 + len(text or "") / 16.0
    return seconds if cap is None else min(cap, seconds)


class _Utterance(object):
    """One queued unit of speech: plain text, or pitched parts to concatenate."""

    __slots__ = ("text", "position", "pitch", "segments", "generation")

    def __init__(self, text="", position=0.0, pitch=0, segments=None):
        self.text = text or ""
        self.position = position
        self.pitch = pitch
        self.segments = segments or ()
        self.generation = 0

    @property
    def has_text(self):
        return bool(self.text) or any(s[0] for s in self.segments)

    @property
    def plain_text(self):
        """The whole utterance as one line (used for pacing and as a fallback)."""
        if not self.segments:
            return self.text
        parts = []
        for seg in self.segments:
            part = (seg[0] or "").strip()
            if part and (not parts or parts[-1] != part):
                parts.append(part)
        return ", ".join(parts)

    @property
    def first_position(self):
        if self.segments:
            try:
                first = self.segments[0]
                return float(first[2]) if len(first) > 2 else 0.0
            except Exception:
                return 0.0
        return self.position


class SpeechAdapter(object):
    """Speech backend implementing :class:`titan_access.contracts.SpeechLike`.

    Titan Access speaks ONLY through Titan's own TTS engine (``tce_speech`` ->
    ``StereoSpeech``), with stereo positioning and pitch. It NEVER speaks through
    ``accessible_output3`` -- regardless of whether stereo speech is enabled in
    settings (that setting only governs positioning, not which engine speaks).
    If Titan TTS is genuinely unavailable it degrades to a plain ``print`` rather
    than ever using ao3.
    """

    # Backend modes.
    _MODE_TCE = "tce"
    _MODE_PRINT = "print"

    # Silence (ms) inserted between parts of a single concatenated announcement
    # (name / type / state). Short but enough to keep the parts distinct on
    # voices that ignore pitch.
    _SEGMENT_GAP_MS = 30

    def __init__(self, settings):
        self._settings = settings
        self._mode = self._MODE_PRINT
        # A StereoSpeech instance dedicated to the reader (see _init_backend).
        self._engine = None

        # Legacy sequence id kept for callers that still bump/read it.
        self._seq_lock = threading.Lock()
        self._seq_id = 0

        # Utterance queue + the single pump thread that drains it. Titan's TTS
        # engines have no queue of their own (every call interrupts), so this is
        # what makes "say this after the current one" actually happen instead of
        # erasing what is playing.
        self._q_lock = threading.Lock()
        self._queue = []
        self._current = None
        self._generation = 0        # bumped by every interrupting call / stop()
        self._pump_thread = None
        self._wake = threading.Event()

        # Fallback "still speaking" estimate when the engine cannot report it.
        self._speaking_until = 0.0

        # Cached getter for the dedicated pygame TTS channel (see
        # :meth:`_tts_channel`). None = not resolved yet, False = unavailable.
        self._tts_channel_getter = None

        self._init_backend()
        # NOTE: the screen reader intentionally does NOT impose its own speech
        # parameters. It speaks through whatever engine / voice / rate / pitch /
        # volume Titan TTS is already configured with, so we do NOT call
        # _apply_levels() here (doing so would override the user's Titan TTS
        # settings with the reader's own defaults).

    # ------------------------------------------------------------------ #
    # Backend selection
    # ------------------------------------------------------------------ #
    def _init_backend(self):
        """Use Titan's own TTS engine -- and ONLY that.

        The reader gets a dedicated ``StereoSpeech`` via
        :func:`tce_speech.get_reader_engine`, which loads the real engine even
        when the ``stereo_speech`` setting is off, WITHOUT changing what engine
        apps/games get (the force is scoped to the reader only). If Titan TTS
        cannot be loaded at all we degrade to console ``print`` -- never ao3.
        """
        try:
            from src.titan_core import tce_speech
            self._engine = tce_speech.get_reader_engine()
            if self._engine is not None:
                self._mode = self._MODE_TCE
                return
        except Exception as e:  # pragma: no cover - depends on host
            print(f"[TitanAccess] Titan TTS unavailable: {e}")

        # No ao3 fallback by design: speak only through Titan TTS, else print.
        self._mode = self._MODE_PRINT

    def _underlying_speaker(self):
        """Return the reader's live ``StereoSpeech`` engine, or None.

        Used only to read :attr:`is_speaking`.
        """
        return self._engine if self._mode == self._MODE_TCE else None

    # ------------------------------------------------------------------ #
    # Capability flags
    # ------------------------------------------------------------------ #
    @property
    def supports_pitch(self):
        """True whenever the active path honours ``pitch_offset``.

        That is the whole Titan TTS path: ``StereoSpeech.speak`` applies the pitch
        offset via the generate path regardless of whether stereo positioning is
        available, so controls are always read with the titan_talk-style
        name/type/state pitch variation. Only the print fallback has no pitch.
        """
        return self._mode == self._MODE_TCE and self._engine is not None

    @property
    def is_speaking(self):
        """Whether speech is playing OR still queued.

        Anything queued counts: a caller asking "are you still talking?" wants
        to know whether the reader has finished what it was asked to say, not
        merely whether audio happens to be flowing this millisecond.
        """
        with self._q_lock:
            if self._queue or self._current is not None:
                return True
        sp = self._underlying_speaker()
        if sp is not None and hasattr(sp, "is_speaking"):
            try:
                return bool(sp.is_speaking)
            except Exception:
                pass
        return time.time() < self._speaking_until

    # ------------------------------------------------------------------ #
    # Speaking (everything goes through the queue + pump)
    # ------------------------------------------------------------------ #
    def _mark_speaking(self, text):
        self._speaking_until = time.time() + _estimate_duration(text)

    def speak(self, text, position=0.0, interrupt=True, pitch_offset=0):
        """Speak ``text``.

        ``interrupt=True`` (the default) drops anything queued and cuts off what
        is playing -- the usual screen-reader "read this now". ``interrupt=False``
        QUEUES the text behind what is already speaking, and the pump guarantees
        it is spoken in turn (see :meth:`_pump`).

        ``position`` is a stereo pan -1..1, ``pitch_offset`` -10..10.
        """
        self._enqueue(_Utterance(text=text, position=position,
                                 pitch=pitch_offset), interrupt)

    # ``speak_async`` is kept because callers all over the reader use it. It has
    # always been the same call: nothing here ever blocks, the pump does the
    # waiting.
    speak_async = speak

    def speak_segments(self, segments):
        """Speak ``(text, pitch_offset, position)`` tuples as ONE announcement.

        Each part keeps its own pitch, and -- this is the contract -- **every**
        part is spoken. Interrupts, like any other element announcement, so
        rapid navigation always reads the newest element.
        """
        segments = [tuple(s) for s in (segments or []) if s and s[0]]
        if not segments:
            return
        self._enqueue(_Utterance(segments=segments), interrupt=True)

    def stop(self):
        """Stop what is speaking and DISCARD everything queued behind it."""
        with self._q_lock:
            self._queue = []
            self._generation += 1
        with self._seq_lock:
            self._seq_id += 1  # invalidate in-flight segment waits
        self._speaking_until = 0.0
        if self._mode == self._MODE_TCE and self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Queue + pump
    # ------------------------------------------------------------------ #
    def _enqueue(self, utterance, interrupt):
        """Add ``utterance`` to the queue (clearing it first when interrupting).

        This is the single entry point for ALL speech. A queue is what makes
        ``interrupt=False`` mean what it says: Titan's TTS engines have no queue
        of their own -- every ``speak``/``speak_async`` stops whatever is
        playing -- so before this, a second announcement simply erased the
        first. Multi-part announcements (and continuous reading) lost everything
        after the part that happened to be playing.
        """
        if not utterance.has_text:
            return
        with self._q_lock:
            if interrupt:
                self._queue = []
                self._generation += 1
            utterance.generation = self._generation
            self._queue.append(utterance)
            self._ensure_pump()
        if interrupt and self._mode == self._MODE_TCE and self._engine is not None:
            # Cut the current audio at once; the pump picks up the new item
            # without waiting for the old one to play out.
            try:
                self._engine.stop()
            except Exception:
                pass
        self._mark_speaking(utterance.plain_text)
        self._wake.set()

    def _ensure_pump(self):
        """Start the pump thread on first use (called with ``_q_lock`` held)."""
        if self._pump_thread is not None and self._pump_thread.is_alive():
            return
        self._pump_thread = threading.Thread(
            target=self._pump, name="TitanAccessSpeechPump", daemon=True)
        self._pump_thread.start()

    def _next_utterance(self):
        with self._q_lock:
            while self._queue:
                item = self._queue.pop(0)
                if item.generation == self._generation:
                    self._current = item
                    return item
            self._current = None
            return None

    def _pump(self):
        """Speak queued utterances one at a time, in order, for ever.

        Each utterance is spoken and then WAITED OUT before the next starts, so
        a queued announcement can neither be cut off by the one behind it nor be
        skipped. An interrupting call empties the queue and bumps the
        generation, which this loop notices at once.
        """
        while True:
            item = self._next_utterance()
            if item is None:
                self._wake.wait(timeout=30.0)
                self._wake.clear()
                continue
            try:
                self._speak_now(item)
            except Exception as e:  # pragma: no cover - never kill the pump
                print(f"[TitanAccess] speech pump error: {e}")
            finally:
                with self._q_lock:
                    if self._current is item:
                        self._current = None

    def _superseded(self, item):
        with self._q_lock:
            return item.generation != self._generation

    def _speak_now(self, item):
        """Render one queued utterance and block until its audio has finished."""
        if self._superseded(item):
            # Interrupted between being taken off the queue and being spoken.
            return
        if self._mode != self._MODE_TCE or self._engine is None:
            print(f"[TitanAccess] (speech) {item.plain_text}")
            return
        eng = self._engine
        if item.segments:
            # Preferred path: let the engine synthesize the pitched parts and
            # play them as ONE concatenated clip with a short silence between
            # them. Because the parts are joined before anything is heard, no
            # part can be cut off by the next one. ``StereoSpeech.speak_concat``
            # does this for every engine that can synthesize to memory (SAPI5,
            # eSpeak, say, and all TitanTTS plugin engines).
            done = False
            if hasattr(eng, "speak_concat"):
                try:
                    done = bool(eng.speak_concat(item.segments,
                                                 gap_ms=self._SEGMENT_GAP_MS))
                except Exception as e:  # pragma: no cover
                    print(f"[TitanAccess] speak_concat error: {e}")
                    done = False
            if not done:
                # An engine that cannot render to memory at all (spd-say, no
                # pydub): speak the parts as a single joined line. The per-part
                # pitch is lost, but the announcement is complete -- which is
                # the whole point. Chaining one interrupting utterance per part
                # (the old fallback) could only be timed correctly for an engine
                # that plays on Titan's pygame TTS channel, so on every other
                # engine the parts after the first were cut off or lost.
                eng.speak_async(item.plain_text,
                                position=item.first_position, pitch_offset=0)
        else:
            eng.speak_async(item.text, position=item.position,
                            pitch_offset=item.pitch)
        self._wait_for_playback(item)

    def _wait_for_playback(self, item):
        """Block until this utterance's audio has finished (or is superseded).

        Pacing signals, in order of reliability: the dedicated pygame TTS
        channel (exact for everything that plays through Titan's mixer), the
        engine's own ``is_speaking``, and finally a length-derived estimate --
        which is all an engine that plays through its own audio device (the
        eSpeak DLL fast path) can offer.
        """
        text = item.plain_text
        est = _estimate_duration(text, cap=None)
        t0 = time.time()
        # Phase 1: wait for the audio to actually start. Synthesis is not
        # instant (a neural engine can take a second), and treating that
        # pre-start silence as "finished" is what let the next utterance
        # interrupt this one before it was ever heard.
        start_cap = t0 + est + 8.0
        started = False
        while time.time() < start_cap:
            if self._superseded(item):
                return
            busy = self._audio_busy()
            if busy:
                started = True
                break
            if busy is None and time.time() - t0 > 0.25:
                break  # no usable signal at all; fall through to the estimate
            time.sleep(0.01)
        if started:
            # Phase 2: playing -- wait for the end, then return at once so the
            # next queued utterance follows with no dead air.
            end_cap = time.time() + est + 30.0
            while time.time() < end_cap:
                if self._superseded(item):
                    return
                busy = self._audio_busy()
                if busy is None or not busy:
                    return
                time.sleep(0.012)
            return
        # No playback signal (engine plays through its own device): pace on the
        # estimate, which is never shortened by a flag we cannot trust.
        remaining = est - (time.time() - t0)
        while remaining > 0:
            if self._superseded(item):
                return
            time.sleep(min(0.05, remaining))
            remaining = est - (time.time() - t0)

    def _audio_busy(self):
        """True/False if a playback signal exists, None when none does."""
        ch = self._tts_channel()
        if ch is not None:
            try:
                return bool(ch.get_busy())
            except Exception:
                pass
        eng = self._engine
        if eng is not None and hasattr(eng, "is_speaking"):
            try:
                return bool(eng.is_speaking)
            except Exception:
                pass
        return None

    def pending_count(self):
        """How many utterances are waiting behind the one being spoken.

        Continuous reading (say all) uses this to stay a line or two ahead of
        the voice: enough that it never runs dry, few enough that a keypress
        interrupts almost immediately.
        """
        with self._q_lock:
            return len(self._queue)

    def wait_for_queue(self, timeout=None):
        """Block until everything queued has been spoken (or ``timeout``).

        Returns True when the queue drained, False on timeout or if speech was
        interrupted. Used by continuous reading (say all).
        """
        deadline = None if timeout is None else time.time() + timeout
        while True:
            with self._q_lock:
                idle = not self._queue and self._current is None
            if idle:
                return True
            if deadline is not None and time.time() > deadline:
                return False
            time.sleep(0.03)

    def wait_until_done(self, text="", timeout=None):
        """Block until everything the reader was asked to say has been said.

        Kept as the public pacing helper for continuous reading; ``text`` is
        accepted (and ignored) so older callers keep working.
        """
        return self.wait_for_queue(timeout=timeout)

    def _tts_channel(self):
        """The dedicated pygame channel Titan TTS plays speech on, or None.

        Polling ``channel.get_busy()`` is the only RELIABLE "is speech still
        playing" signal: on the fast eSpeak DLL path ``is_speaking`` flips back to
        False ~20 ms in while the audio plays for seconds, but this channel
        tracks the real playback exactly -- and, being the reserved TTS channel,
        it excludes the cursor / list-item cues (they play on other channels), so
        we pace on speech alone. Resolved lazily; ``False`` once we know the host
        has no such channel (standalone reader / non-pygame backend)."""
        getter = self._tts_channel_getter
        if getter is False:
            return None
        if getter is None:
            try:
                from src.titan_core.sound import get_tts_channel
                getter = get_tts_channel
                self._tts_channel_getter = getter
            except Exception:
                self._tts_channel_getter = False
                return None
        try:
            return getter()
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Configuration (mirrors C# SpeechManager setters)
    # ------------------------------------------------------------------ #
    def set_rate(self, rate):
        """Set speech rate (-10 slow .. 10 fast)."""
        if self._mode == self._MODE_TCE and self._engine is not None:
            try:
                self._engine.set_rate(int(rate))
            except Exception:
                pass

    def set_volume(self, volume):
        """Set speech volume (0 .. 100)."""
        if self._mode == self._MODE_TCE and self._engine is not None:
            try:
                self._engine.set_volume(int(volume))
            except Exception:
                pass

    def set_pitch(self, pitch):
        """Set base voice pitch (-10 .. 10). Honoured only on the Titan path."""
        if self._mode == self._MODE_TCE and self._engine is not None:
            try:
                self._engine.set_pitch(int(pitch))
            except Exception:
                pass

    def set_engine(self, name):
        """Select a TTS engine by name.

        Accepts either a Titan engine id (``espeak``/``sapi5``/...) or one of the
        screen reader's ``Synthesizer`` names (``SAPI5``/``OneCore``/...), which
        are mapped to the nearest Titan engine.
        """
        if self._mode != self._MODE_TCE or self._engine is None or not name:
            return
        key = str(name).strip().lower()
        engine = _SYNTH_TO_ENGINE.get(key, key)
        try:
            self._engine.set_engine(engine)
        except Exception:
            pass

    def set_voice(self, voice):
        """Select a voice by index (int) or by id / display name (str)."""
        if self._mode != self._MODE_TCE or self._engine is None or voice in (None, ""):
            return
        try:
            if isinstance(voice, int):
                self._engine.set_voice(voice)
                return
            # Resolve a name / id against the available voice list.
            voices = self._engine.get_available_voices() or []
            for i, v in enumerate(voices):
                if isinstance(v, dict):
                    if voice in (v.get("id"), v.get("display_name"), v.get("name")):
                        self._engine.set_voice(i)
                        return
                elif str(v) == str(voice):
                    self._engine.set_voice(i)
                    return
        except Exception:
            pass

    def get_voices(self):
        """Return the available voices for the current engine (names or dicts)."""
        if self._mode == self._MODE_TCE and self._engine is not None:
            try:
                return list(self._engine.get_available_voices() or [])
            except Exception:
                pass
        return []

    def get_engines(self):
        """Return the TTS engines Titan exposes (empty on the ao3 fallback)."""
        if self._mode == self._MODE_TCE and self._engine is not None:
            try:
                return list(self._engine.get_available_engines() or [])
            except Exception:
                pass
        return []

    # ------------------------------------------------------------------ #
    # Settings application
    # ------------------------------------------------------------------ #
    def _apply_levels(self):
        """Push the numeric rate / volume / pitch from settings to the engine."""
        try:
            self.set_rate(self._settings.rate)
            self.set_volume(self._settings.volume)
            self.set_pitch(self._settings.pitch)
        except Exception as e:  # pragma: no cover
            print(f"[TitanAccess] speech level apply error: {e}")

    def apply_settings(self):
        """No-op for speech parameters.

        Speech (engine / voice / rate / pitch / volume) is owned by Titan TTS and
        configured in Titan's own settings, not by the screen reader. This method
        is kept so callers (the settings panel) can invoke it safely, but it
        deliberately does not override any Titan TTS parameter.
        """
        return


# --------------------------------------------------------------------------- #
# Module factory
# --------------------------------------------------------------------------- #
def get_speech(settings):
    """Build a :class:`SpeechAdapter` for the given settings store."""
    return SpeechAdapter(settings)
