# -*- coding: utf-8 -*-
"""Speech output for Titan Access.

Python port of the C# ``ScreenReader.SpeechManager``. Instead of re-implementing
SAPI5 / OneCore / BestSpeech and the bespoke NAudio stereo capture, this adapter
delegates to **Titan's own configured TTS engine** (:mod:`src.titan_core.tce_speech`),
which already provides:

* a configurable synthesizer (eSpeak / SAPI5 / ElevenLabs / ...),
* true stereo positioning (``position`` -1.0 left .. 1.0 right), and
* additive pitch control (``pitch_offset`` -10 .. 10),

mirroring exactly what ``SpeechManager.SpeakStereo`` did by hand. When Titan TTS
is unavailable (running the reader standalone, or Titan's stereo speech disabled)
it degrades to ``accessible_output3`` and finally to a plain ``print`` so the
screen reader never hard-crashes on a missing dependency.

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
_SYNTH_TO_ENGINE = {
    "sapi5": "sapi5",
    "onecore": "sapi5",       # nearest Windows-native equivalent
    "bestspeech": "espeak",
}


def _estimate_duration(text):
    """Rough spoken duration (seconds) used to gate sequential segments.

    Matches the heuristic in ``titan_talk.tt_core`` so segment pacing feels the
    same across the suite when the engine cannot report :attr:`is_speaking`.
    """
    return min(2.5, 0.28 + len(text or "") / 16.0)


class SpeechAdapter(object):
    """Speech backend implementing :class:`titan_access.contracts.SpeechLike`.

    Prefers Titan's ``tce_speech`` (stereo + pitch). Falls back to
    ``accessible_output3`` (no pitch), then to ``print``.
    """

    # Backend modes.
    _MODE_TCE = "tce"
    _MODE_AO3 = "ao3"
    _MODE_PRINT = "print"

    def __init__(self, settings):
        self._settings = settings
        self._mode = self._MODE_PRINT
        self._tce = None
        self._ao3 = None

        # Sequence id for :meth:`speak_segments` (a newer call supersedes an
        # in-flight one) — same pattern as titan_talk.
        self._seq_lock = threading.Lock()
        self._seq_id = 0

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
        """Pick the best available speech backend, most capable first."""
        # 1) Titan's configured TTS engine.
        try:
            from src.titan_core import tce_speech
            self._tce = tce_speech
            self._mode = self._MODE_TCE
            return
        except Exception as e:  # pragma: no cover - depends on host
            print(f"[TitanAccess] tce_speech unavailable: {e}")

        # 2) accessible_output3 (screen-reader / SAPI bridge, no pitch).
        try:
            import accessible_output3.outputs.auto
            self._ao3 = accessible_output3.outputs.auto.Auto()
            self._mode = self._MODE_AO3
            return
        except Exception as e:  # pragma: no cover
            print(f"[TitanAccess] accessible_output3 unavailable: {e}")

        # 3) Last resort: print to the console.
        self._mode = self._MODE_PRINT

    def _underlying_speaker(self):
        """Return Titan's live speaker object (StereoSpeech) when present.

        Used only to read :attr:`is_speaking`; ``None`` for the other backends.
        """
        if self._mode == self._MODE_TCE and self._tce is not None:
            return getattr(self._tce, "_speaker", None)
        return None

    # ------------------------------------------------------------------ #
    # Capability flags
    # ------------------------------------------------------------------ #
    @property
    def supports_pitch(self):
        """True whenever the active path honours ``pitch_offset``.

        That is the whole Titan TTS path: ``tce_speech.speak`` applies the pitch
        offset via the generate path regardless of whether stereo positioning is
        available, so controls are always read with the titan_talk-style
        name/type/state pitch variation. Only ``accessible_output3`` and the
        print fallback have no pitch control.
        """
        return self._mode == self._MODE_TCE and self._tce is not None

    @property
    def is_speaking(self):
        """Whether speech is currently playing.

        Prefers the engine's own flag (StereoSpeech exposes ``is_speaking``);
        otherwise uses the duration estimate set on the last utterance.
        """
        sp = self._underlying_speaker()
        if sp is not None and hasattr(sp, "is_speaking"):
            try:
                return bool(sp.is_speaking)
            except Exception:
                pass
        return time.time() < self._speaking_until

    # ------------------------------------------------------------------ #
    # Speaking
    # ------------------------------------------------------------------ #
    def _mark_speaking(self, text):
        self._speaking_until = time.time() + _estimate_duration(text)

    def speak(self, text, position=0.0, interrupt=True, pitch_offset=0):
        """Speak ``text`` (blocking only for the print fallback).

        ``position`` is a stereo pan -1..1, ``pitch_offset`` -10..10 (ignored by
        the non-Titan backends).
        """
        if not text:
            return
        if self._mode == self._MODE_TCE:
            try:
                self._tce.speak(text, position=position, interrupt=interrupt,
                                pitch_offset=pitch_offset)
                self._mark_speaking(text)
                return
            except Exception as e:  # pragma: no cover
                print(f"[TitanAccess] tce_speech.speak error: {e}")
        if self._mode == self._MODE_AO3 and self._ao3 is not None:
            try:
                self._ao3.speak(text, interrupt=interrupt)
                self._mark_speaking(text)
                return
            except Exception as e:  # pragma: no cover
                print(f"[TitanAccess] ao3.speak error: {e}")
        print(f"[TitanAccess] (speech) {text}")

    def speak_async(self, text, position=0.0, interrupt=True, pitch_offset=0):
        """Non-blocking variant of :meth:`speak`."""
        if not text:
            return
        if self._mode == self._MODE_TCE:
            try:
                self._tce.speak_async(text, position=position, interrupt=interrupt,
                                      pitch_offset=pitch_offset)
                self._mark_speaking(text)
                return
            except Exception as e:  # pragma: no cover
                print(f"[TitanAccess] tce_speech.speak_async error: {e}")
        # ao3 / print fallbacks have no async API; spawn a thread.
        threading.Thread(
            target=self.speak,
            args=(text, position, interrupt, pitch_offset),
            daemon=True,
        ).start()

    def stop(self):
        """Stop any current speech and supersede any pending segment sequence."""
        with self._seq_lock:
            self._seq_id += 1  # invalidate in-flight speak_segments
        self._speaking_until = 0.0
        if self._mode == self._MODE_TCE and self._tce is not None:
            try:
                self._tce.stop()
                return
            except Exception:
                pass
        if self._mode == self._MODE_AO3 and self._ao3 is not None:
            # accessible_output3 outputs expose silence(); guard for safety.
            for attr in ("silence", "stop"):
                fn = getattr(self._ao3, attr, None)
                if callable(fn):
                    try:
                        fn()
                        return
                    except Exception:
                        pass

    # ------------------------------------------------------------------ #
    # Sequential pitched announcement (name / type / state)
    # ------------------------------------------------------------------ #
    def speak_segments(self, segments):
        """Speak ``(text, pitch_offset, position)`` tuples sequentially.

        Each segment is fully spoken at its own pitch before the next begins. A
        newer call bumps the sequence id so rapid navigation cleanly supersedes
        an in-flight sequence (its first segment interrupts whatever is playing).
        Port of ``titan_talk.tt_core.speak_segments``.
        """
        segments = [s for s in (segments or []) if s and s[0]]
        if not segments:
            return
        with self._seq_lock:
            self._seq_id += 1
            my_id = self._seq_id
        threading.Thread(target=self._run_segments, args=(my_id, segments),
                         daemon=True).start()

    def _run_segments(self, my_id, segments):
        for text, pitch, position in segments:
            if not text:
                continue
            with self._seq_lock:
                if my_id != self._seq_id:
                    return
            # Every segment interrupts the previous one (which has already had
            # its full time slice below): the first cuts off the previous
            # announcement, the rest play back-to-back.
            self.speak_async(text, position=position, interrupt=True,
                             pitch_offset=pitch)
            self._wait_for_segment(text, my_id)

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

    def _wait_for_segment(self, text, my_id):
        """Block until a segment's audio has finished, then return at once.

        CRITICAL: every segment is spoken with ``interrupt=True`` so that the
        FIRST segment of a new announcement cuts off the previous one. That makes
        the inter-segment wait load-bearing: if it returns too early, the *next*
        segment's interrupt cuts the *current* one mid-word. The element name is
        the first segment, so an early return here is exactly what made the name
        come out as silence or a clipped syllable ("element listy" with no name).

        We pace on the real audio: poll the dedicated TTS channel's
        ``get_busy()`` (see :meth:`_tts_channel`) and move on the instant the clip
        ends -- so pauses are exactly as long as the speech, no dead air, and the
        segment is never cut. We do NOT trust ``is_speaking`` (it lies on the
        eSpeak DLL path). When no channel signal is available (standalone reader)
        we fall back to a fixed length-derived estimate, never shortened by a
        playback flag.

        A newer announcement (bumped sequence id) supersedes us within one poll,
        so rapid navigation stays responsive (each keypress interrupts).
        """
        est = _estimate_duration(text)

        def _superseded():
            with self._seq_lock:
                return my_id != self._seq_id

        def _ch_busy():
            ch = self._tts_channel()
            if ch is None:
                return None
            try:
                return bool(ch.get_busy())
            except Exception:
                return None

        # Let the new utterance take over the channel: interrupt stops the old
        # sound, then synthesis hands the new clip to the channel (~10-20 ms on
        # the eSpeak DLL path).
        t0 = time.time()
        time.sleep(0.04)

        probe = _ch_busy()
        if probe is None:
            # No playback signal (standalone / non-pygame backend): fixed
            # length-derived estimate. NEVER gate on is_speaking here.
            slept = 0.04
            while slept < est:
                if _superseded():
                    return
                time.sleep(0.03)
                slept += 0.03
            return

        # A short floor before we trust "channel idle". The element cue (a
        # high/low earcon) can briefly grab the TTS channel just before the first
        # segment, so right after dispatch the channel may read busy-from-the-cue
        # and then idle in the gap before speech actually starts -- without this
        # floor phase 2 would see that gap, return, and the next segment's
        # interrupt would cut the NAME (heard as: cue tone, short pause, then only
        # the control type). Speech audio is contiguous once it starts, so a
        # floor that outlasts the cue gap is enough; bounded by the estimate so a
        # genuinely short clip adds no real dead air.
        floor = min(est, 0.22)

        # Phase 1: wait for the clip to actually START on the TTS channel (cap so
        # a missed start never hangs us).
        started = bool(probe)
        start_deadline = time.time() + max(0.5, est)
        while not started and time.time() < start_deadline:
            if _superseded():
                return
            b = _ch_busy()
            if b:
                started = True
                break
            if b is None:
                break
            time.sleep(0.01)

        # Phase 2: wait for the clip to END (and the floor to pass), then the next
        # segment plays at once. Generous cap as a safety net (long line read).
        end_deadline = time.time() + est + 2.0
        while time.time() < end_deadline:
            if _superseded():
                return
            b = _ch_busy()
            if (b is None or not b) and (time.time() - t0) >= floor:
                return
            time.sleep(0.012)

    # ------------------------------------------------------------------ #
    # Configuration (mirrors C# SpeechManager setters)
    # ------------------------------------------------------------------ #
    def set_rate(self, rate):
        """Set speech rate (-10 slow .. 10 fast)."""
        if self._mode == self._MODE_TCE and self._tce is not None:
            try:
                self._tce.set_rate(int(rate))
            except Exception:
                pass

    def set_volume(self, volume):
        """Set speech volume (0 .. 100)."""
        if self._mode == self._MODE_TCE and self._tce is not None:
            try:
                self._tce.set_volume(int(volume))
            except Exception:
                pass

    def set_pitch(self, pitch):
        """Set base voice pitch (-10 .. 10). Honoured only on the Titan path."""
        if self._mode == self._MODE_TCE and self._tce is not None:
            try:
                self._tce.set_pitch(int(pitch))
            except Exception:
                pass

    def set_engine(self, name):
        """Select a TTS engine by name.

        Accepts either a Titan engine id (``espeak``/``sapi5``/...) or one of the
        screen reader's ``Synthesizer`` names (``SAPI5``/``OneCore``/...), which
        are mapped to the nearest Titan engine.
        """
        if self._mode != self._MODE_TCE or self._tce is None or not name:
            return
        key = str(name).strip().lower()
        engine = _SYNTH_TO_ENGINE.get(key, key)
        try:
            self._tce.set_engine(engine)
        except Exception:
            pass

    def set_voice(self, voice):
        """Select a voice by index (int) or by id / display name (str)."""
        if self._mode != self._MODE_TCE or self._tce is None or voice in (None, ""):
            return
        try:
            if isinstance(voice, int):
                self._tce.set_voice(voice)
                return
            # Resolve a name / id against the available voice list.
            voices = self._tce.get_available_voices() or []
            for i, v in enumerate(voices):
                if isinstance(v, dict):
                    if voice in (v.get("id"), v.get("display_name"), v.get("name")):
                        self._tce.set_voice(i)
                        return
                elif str(v) == str(voice):
                    self._tce.set_voice(i)
                    return
        except Exception:
            pass

    def get_voices(self):
        """Return the available voices for the current engine (names or dicts)."""
        if self._mode == self._MODE_TCE and self._tce is not None:
            try:
                return list(self._tce.get_available_voices() or [])
            except Exception:
                pass
        return []

    def get_engines(self):
        """Return the TTS engines Titan exposes (empty on the ao3 fallback)."""
        if self._mode == self._MODE_TCE and self._tce is not None:
            try:
                return list(self._tce.get_available_engines() or [])
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
