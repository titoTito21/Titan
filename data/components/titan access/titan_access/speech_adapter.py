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
import os
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


def _engine_offered(engine, name):
    """Whether *engine* lists *name* (or its Titan spelling) as available.
    An engine that cannot say is believed."""
    asked = _SYNTH_TO_ENGINE.get(str(name).lower(), str(name))
    try:
        offered = engine.get_available_engines()
    except Exception:                                # noqa: BLE001
        return True
    names = set()
    for one in offered or []:
        if isinstance(one, dict):
            one = one.get("id") or one.get("name") or ""
        names.add(str(one).lower())
    if not names:
        return True
    return asked.lower() in names or str(name).lower() in names \
        or (asked.lower() == "sapi5" and "sapi5_32" in names)


def _estimate_duration(text, cap=2.5):
    """Rough spoken duration (seconds) used to pace speech.

    Matches the heuristic in ``titan_talk.tt_core`` so pacing feels the same
    across the suite when the engine cannot report :attr:`is_speaking`. Pass
    ``cap=None`` when the estimate has to cover a whole utterance (the queue
    pump): capping it at 2.5 s would start the next one over a long sentence.
    """
    seconds = 0.28 + len(text or "") / 16.0
    return seconds if cap is None else min(cap, seconds)



import collections as _collections
_SPOKEN = _collections.deque(maxlen=20)
_TRACE = bool(os.environ.get("TITAN_ACCESS_TRACE"))


def spoken():
    """The last twenty things the reader was asked to say, oldest first."""
    return list(_SPOKEN)

class _Utterance(object):
    """One queued unit of speech: plain text, or pitched parts to concatenate."""

    __slots__ = ("text", "position", "pitch", "segments", "generation",
                 "gap_ms", "voice")

    def __init__(self, text="", position=0.0, pitch=0, segments=None,
                 gap_ms=0, voice=None):
        self.text = text or ""
        self.position = position
        self.pitch = pitch
        self.segments = segments or ()
        self.generation = 0
        # The silence between the parts a speech scheme asks for, over the
        # engine's own small default - a scheme's pacing, heard.
        self.gap_ms = int(gap_ms or 0)
        # A voice class's profile for a WHOLE utterance: a synthesizer of
        # its own, a voice, dials. Put on the private engine for this
        # utterance and taken off again once it has been heard.
        self.voice = dict(voice) if voice else None

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
            if self._own_voice_wanted():
                # **A voice of the reader's own.** A private engine, never
                # the one Titan's apps and games speak through, configured
                # from the Speech section of this reader's settings.
                self._engine = tce_speech.get_private_reader_engine()
                if self._engine is not None:
                    self._own = True
                    self._apply_own_voice()
            if self._engine is None:
                self._engine = tce_speech.get_reader_engine()
            if self._engine is not None:
                self._mode = self._MODE_TCE
                return
        except Exception as e:  # pragma: no cover - depends on host
            print(f"[TitanAccess] Titan TTS unavailable: {e}")

        # No ao3 fallback by design: speak only through Titan TTS, else print.
        self._mode = self._MODE_PRINT

    # ------------------------------------------------------------------ #
    # The reader's own voice
    # ------------------------------------------------------------------ #
    def _own_voice_wanted(self):
        try:
            return bool(self._settings.get_bool("Speech", "OwnVoice", False))
        except Exception:
            return False

    def _apply_own_voice(self):
        """Engine, voice, rate, pitch and volume from the Speech section."""
        engine = self._engine
        if engine is None:
            return
        st = self._settings
        try:
            wanted = str(st.get("Speech", "Synthesizer", "") or "")
            # **Only a synthesizer this platform offers.** The store's
            # default is SAPI5, which a Linux Titan refuses ("not available
            # on this platform") every time the voice is put back after a
            # borrowed part - the refusal is logged and the engine left
            # wherever the borrower put it. A name the engine does not
            # list is not set, and what it is running stays.
            if wanted and hasattr(engine, "set_engine") and \
                    _engine_offered(engine, wanted):
                engine.set_engine(wanted)
            # **speech-dispatcher's synthesizer is its output module**, and
            # the voice list depends on it - so the module goes on before
            # the voice is looked for.
            if str(getattr(engine, "engine", "") or "") == "spd" and \
                    hasattr(engine, "set_spd_module"):
                engine.set_spd_module(str(st.get(
                    "Speech", "SpeechDispatcherModule", "") or ""))
            voice = str(st.get("Speech", "Voice", "") or "")
            if voice and hasattr(engine, "set_voice"):
                # **By id, by display name, by name, then by index.** The
                # settings panel stores a voice's ID, and a Titan TTS
                # engine's voices are dicts with `id` and `display_name` -
                # neither of which is `name`, so the saved voice matched
                # nothing and every Titan TTS engine spoke in its FIRST
                # voice whatever had been chosen.
                at = _voice_index(engine, voice)
                if at is not None:
                    engine.set_voice(at)
            for key, setter, default in (("Rate", "set_rate", 0),
                                         ("Pitch", "set_pitch", 0),
                                         ("Volume", "set_volume", 100)):
                value = st.get_int("Speech", key, default)
                if hasattr(engine, setter):
                    getattr(engine, setter)(int(value))
        except Exception as e:
            print(f"[TitanAccess] own voice: {e}")

    def apply_settings(self):
        """Re-read the reader's settings. The voice is the part that can
        change: turning the reader's own voice on or off swaps the engine,
        and a changed rate or voice is put onto the private one."""
        try:
            from src.titan_core import tce_speech
        except Exception:
            return
        wanted = self._own_voice_wanted()
        if wanted and not getattr(self, "_own", False):
            engine = tce_speech.get_private_reader_engine()
            if engine is not None:
                self._engine, self._own = engine, True
                self._mode = self._MODE_TCE
        elif not wanted and getattr(self, "_own", False):
            engine = tce_speech.get_reader_engine()
            if engine is not None:
                self._engine, self._own = engine, False
        if getattr(self, "_own", False):
            self._apply_own_voice()
        external = self._external_synth()
        if external:
            self._apply_external(external)

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

    def speak(self, text, position=0.0, interrupt=True, pitch_offset=0,
              voice=None):
        """Speak ``text``.

        ``interrupt=True`` (the default) drops anything queued and cuts off what
        is playing -- the usual screen-reader "read this now". ``interrupt=False``
        QUEUES the text behind what is already speaking, and the pump guarantees
        it is spoken in turn (see :meth:`_pump`).

        ``position`` is a stereo pan -1..1, ``pitch_offset`` -10..10.
        ``voice`` is a voice class's whole profile (``synth``, ``voice``,
        ``rate``, ``pitch``, ``volume``): the utterance is spoken by THAT
        synthesizer in that voice, and the reader's own is put back after.
        """
        self._enqueue(_Utterance(text=text, position=position,
                                 pitch=pitch_offset, voice=voice), interrupt)

    # ``speak_async`` is kept because callers all over the reader use it. It has
    # always been the same call: nothing here ever blocks, the pump does the
    # waiting.
    speak_async = speak

    def speak_segments(self, segments, gap_ms=0):
        """Speak ``(text, pitch_offset, position)`` tuples as ONE announcement.

        Each part keeps its own pitch, and -- this is the contract -- **every**
        part is spoken. Interrupts, like any other element announcement, so
        rapid navigation always reads the newest element. ``gap_ms`` is the
        silence between the parts a speech scheme asks for.
        """
        segments = [tuple(s) for s in (segments or []) if s and s[0]]
        if not segments:
            return
        self._enqueue(_Utterance(segments=segments, gap_ms=gap_ms),
                      interrupt=True)

    # ------------------------------------------------------------------ #
    # Pausing - Shift, as in NVDA: speech holds where it is and goes on
    # from there, rather than being thrown away as Control throws it away
    # ------------------------------------------------------------------ #
    paused = False

    def pause(self, switch):
        """Hold speech (True) or let it go on (False)."""
        switch = bool(switch)
        if switch == self.paused:
            return False
        self.paused = switch
        external = self._external_synth()
        if external:
            try:
                from .nvda_host import external as _external
                _external.pause(external, switch)
            except Exception:
                pass
        channel = self._tts_channel()
        if channel is not None:
            try:
                channel.pause() if switch else channel.unpause()
            except Exception:
                pass
        if not switch:
            self._wake.set()
        return True

    def toggle_pause(self):
        """Pause what is being said, or go on with it. ``True`` when the
        speech is paused now."""
        if not self.paused and not self.is_speaking:
            return False
        self.pause(not self.paused)
        return self.paused

    def stop(self):
        """Stop what is speaking and DISCARD everything queued behind it."""
        if self.paused:
            # Stopping ends a pause too: what was held is thrown away.
            self.pause(False)
        with self._q_lock:
            self._queue = []
            self._generation += 1
        with self._seq_lock:
            self._seq_id += 1  # invalidate in-flight segment waits
        self._speaking_until = 0.0
        external = self._external_synth()
        if external:
            try:
                from .nvda_host import external as _external
                _external.stop(external)
            except Exception:
                pass
        if self._mode == self._MODE_TCE and self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass

    def shutdown(self):
        """**Off means off**: the reader has been switched off, so nothing
        of its voice may go on running in Titan's process.

        What is stopped: the queue and the pump thread, and - when the
        reader had a voice of its own - its PRIVATE engine with everything
        that engine started: its SAPI worker (and the 32-bit cscript bridge
        behind it) and the Titan TTS bridges (DECtalk, Eloquence, SMP,
        Festival are each an .exe with a console of its own). Measured
        before this: four bridge processes, four conhosts, the SAPI worker
        and the pump were all still running after the reader said it was
        off.

        The bridges are shut only when nothing else speaks through them:
        the engine registry is shared, and when Titan's own speech has an
        engine of its own those processes are Titan's, not the reader's.
        """
        self._closed = True
        try:
            self.stop()
        except Exception:                            # noqa: BLE001
            pass
        self._wake.set()
        pump = self._pump_thread
        if pump is not None and pump.is_alive() and \
                pump is not threading.current_thread():
            pump.join(timeout=2.0)
        self._pump_thread = None
        if not getattr(self, '_own', False):
            return
        engine, self._engine = self._engine, None
        self._mode = self._MODE_PRINT
        release_private_engine(engine)

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
        # **What was said is written down** (`spoken`, the last twenty),
        # and printed when ``TITAN_ACCESS_TRACE`` is set: "the reader says
        # nothing about the list" is a report with no evidence in it, and
        # a log of synthesiser timings says nothing about the words.
        try:
            said = utterance.text if utterance.text else " / ".join(
                str(seg[0]) for seg in (utterance.segments or []))
            _SPOKEN.append(said)
            if _TRACE:
                print(f"[TitanAccess] said: {said}", flush=True)
        except Exception:
            pass
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

    def _hold_while_paused(self):
        while self.paused:
            time.sleep(0.05)

    def _pump(self):
        """Speak queued utterances one at a time, in order, for ever.

        Each utterance is spoken and then WAITED OUT before the next starts, so
        a queued announcement can neither be cut off by the one behind it nor be
        skipped. An interrupting call empties the queue and bumps the
        generation, which this loop notices at once.
        """
        while not getattr(self, '_closed', False):
            item = self._next_utterance()
            if item is None:
                self._wake.wait(timeout=30.0)
                self._wake.clear()
                continue
            try:
                # A pause holds the NEXT utterance too - pausing is "wait",
                # not "skip this one".
                self._hold_while_paused()
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
        # **Parts with voices of their own** are spoken group by group,
        # each on the synthesizer its class asks for - which may be an
        # NVDA add-on synthesizer as well as one of Titan's engines.
        if item.segments and any(
                profile is not None
                for profile, _parts in self._groups(item.segments)):
            self._speak_groups(item)
            return
        # **A borrowed voice is resolved against the reader's own
        # synthesizer first**: a class that names a voice and no
        # synthesizer means a voice of the one the reader speaks with.
        # Without that, a class voice under an external reader went to
        # Titan's engine (or was dropped), and a class voice of an NVDA
        # add-on synthesizer was a `set_engine('nvda:...')` the engine
        # refused, so the sample came out in the wrong voice.
        profile = self._resolve(item.voice) if item.voice else None
        borrowed_external = _external_profile(profile)
        if borrowed_external:
            self._speak_external(borrowed_external, item, profile)
            return
        external = self._external_synth()
        if external and not profile:
            self._speak_external(external, item)
            return
        if self._mode != self._MODE_TCE or self._engine is None:
            print(f"[TitanAccess] (speech) {item.plain_text}")
            return
        if not profile:
            self._render(item, self._engine)
            return
        eng = self._voice_engine(profile)
        borrowed = self._borrow_on(eng, profile)
        try:
            self._render(item, eng)
        finally:
            if borrowed:
                self._give_voice_back_on(eng)

    def reader_synth(self):
        """The synthesizer the reader speaks with now, in the spelling
        `speech_systems` lists it under ('nvda:x', 'spd:module', an engine
        id), or '' when it cannot be said."""
        external = self._external_synth()
        if external:
            return external
        engine = self._engine
        name = str(getattr(engine, "engine", "") or "") if engine else ""
        if name == "spd":
            return "spd:%s" % str(getattr(engine, "spd_module", "") or "")
        return name

    def _resolve(self, profile):
        """A class's voice profile with its synthesizer filled in: the
        reader's own where it names none, and speech-dispatcher's
        ``spd:<module>`` split into the engine and its module."""
        profile = dict(profile or {})
        synth = str(profile.get("synth") or "").strip()
        if not synth:
            synth = self.reader_synth()
        if synth.startswith("spd:"):
            profile.setdefault("spd_module", synth[4:])
            synth = "spd"
        if synth:
            profile["synth"] = synth
        else:
            profile.pop("synth", None)
        return profile

    def _speak_groups(self, item):
        """The parts of one announcement, each group on its own
        synthesizer, in order; an interrupt between groups cuts the rest."""
        import copy
        own_external = self._external_synth()
        for profile, parts in self._groups(item.segments):
            if self._superseded(item):
                return
            piece = copy.copy(item)
            piece.segments = list(parts)
            resolved = self._resolve(profile) if profile else None
            target = _external_profile(resolved) if resolved else own_external
            try:
                if target:
                    self._speak_external(target, piece, resolved)
                elif self._mode == self._MODE_TCE and \
                        self._engine is not None:
                    if resolved:
                        self._render_group(piece, piece.segments, resolved)
                    else:
                        self._render(piece, self._engine)
                else:
                    print(f"[TitanAccess] (speech) {piece.plain_text}")
            except Exception as e:                   # noqa: BLE001
                print(f"[TitanAccess] voice group: {e}")

    # ------------------------------------------------------------------ #
    # External synthesis - an NVDA add-on's synthesizer (`nvda_host`)
    # ------------------------------------------------------------------ #
    def _external_synth(self):
        """The external synthesizer the reader speaks with, or ''."""
        if not self._own_voice_wanted():
            return ""
        wanted = str(self._settings.get("Speech", "Synthesizer", "") or "")
        return wanted if wanted.startswith("nvda:") else ""

    def _speak_external(self, synth_id, item, profile=None):
        restore = None
        try:
            from .nvda_host import external
            # The reader's own synthesizer is told its voice before its first
            # word: speech that starts before the settings are applied (the
            # start-up announcement) made the instance on its default voice.
            if synth_id not in external._wanted and \
                    synth_id == self._external_synth():
                self._apply_external(synth_id, warm=False)
            if profile:
                restore = self._lend_external(synth_id, profile)
            if item.segments:
                parts = [(seg[0], seg[1] if len(seg) > 1 else 0)
                         for seg in item.segments]
            else:
                parts = [(item.text, item.pitch)]
            self._mark_speaking(item.plain_text)
            stalled_before = external.report().get('stalled', 0)
            said = external.speak_parts(synth_id, parts,
                                 cancelled=lambda: self._superseded(item),
                                 gap_ms=max(self._SEGMENT_GAP_MS,
                                            int(item.gap_ms or 0))
                                 if item.segments else 0,
                                 paused=lambda: self.paused)
            if not said and not self._superseded(item) and \
                    external.report().get('stalled', 0) > stalled_before:
                # **The words are not lost with the synthesizer.** One that
                # stopped answering is started again for the next word;
                # this one is said in Titan's own voice, so the reader is
                # never silent while that happens.
                self._say_in_titans_voice(item)
        except Exception as e:
            print(f"[TitanAccess] external synthesis: {e}")
            print(f"[TitanAccess] (speech) {item.plain_text}")
            self._say_in_titans_voice(item)
        finally:
            if restore is not None:
                restore()

    def _say_in_titans_voice(self, item):
        engine = self._engine
        if engine is None or self._mode != self._MODE_TCE:
            return
        try:
            self._render(item, engine)
        except Exception as e:                       # noqa: BLE001
            print(f"[TitanAccess] fallback voice: {e}")

    def _lend_external(self, synth_id, profile):
        """Put a borrowed voice and variant on an external synthesizer for
        one utterance; answers what puts the reader's own back."""
        from .nvda_host import external
        voice = str(profile.get("voice") or "")
        variant = str(profile.get("variant") or "")
        if voice:
            external.set_voice(synth_id, voice)
        if variant:
            external.set_variant(synth_id, variant)
        # **The class's rate and volume ride on the reader's own levels**,
        # as they do on Titan's engines (`_borrow_voice`); the pitch is
        # per part and goes with the parts.
        st = self._settings
        try:
            rate = st.get_int("Speech", "Rate", 0) + int(
                profile.get("rate") or 0)
            volume = st.get_int("Speech", "Volume", 100) + 5 * int(
                profile.get("volume") or 0)
            external.set_levels(
                synth_id, rate=50 + max(-10, min(10, rate)) * 5,
                pitch=50 + int(st.get_int("Speech", "Pitch", 0)) * 5,
                volume=max(0, min(100, volume)))
        except Exception as e:                       # noqa: BLE001
            print(f"[TitanAccess] class levels: {e}")
        own = self._external_synth()

        def back():
            if own == synth_id:
                self._apply_external(synth_id, warm=False)
        return back

    def _apply_external(self, synth_id, warm=True):
        """The reader's voice, variant and levels, on the external
        synthesizer."""
        st = self._settings
        try:
            from .nvda_host import external
            voice = str(st.get("Speech", "Voice", "") or "")
            if voice:
                external.set_voice(synth_id, voice)
            # **The variant after the voice**: it belongs to the voice
            # (Cerence's compact / embedded-pro / embedded-high), and a
            # voice put on afterwards would load its own default over it.
            variant = str(st.get("Speech", "Variant", "") or "")
            if variant:
                external.set_variant(synth_id, variant)
            rate = st.get_int("Speech", "Rate", 0)
            pitch = st.get_int("Speech", "Pitch", 0)
            volume = st.get_int("Speech", "Volume", 100)
            external.set_levels(synth_id, rate=50 + int(rate) * 5,
                                pitch=50 + int(pitch) * 5, volume=volume)
            if warm:
                external.warm(synth_id)
        except Exception as e:
            print(f"[TitanAccess] external synthesis settings: {e}")

    def _borrow_voice(self, profile):
        """Put a class's own synthesizer and voice on the private engine
        for one utterance. True when anything was changed."""
        if not profile:
            return False
        engine = self._engine
        if engine is None:
            return False
        changed = False
        try:
            synth = str(profile.get("synth") or "").strip()
            if synth.startswith("spd:"):
                profile = dict(profile)
                profile.setdefault("spd_module", synth[4:])
                synth = "spd"
            # **Only switched when it is another engine**: switching an
            # engine to itself reloads it, and a class that names the
            # synthesizer the reader already speaks with wants its voice,
            # not a reload per part.
            if synth and hasattr(engine, "set_engine"):
                target = _SYNTH_TO_ENGINE.get(synth.lower(), synth)
                if str(getattr(engine, "engine", "") or "").lower() != \
                        target.lower():
                    engine.set_engine(target)
                    changed = True
            # speech-dispatcher's synthesizer is a MODULE of one engine;
            # the speech system dialog's Test hands it over this way.
            if "spd_module" in profile and hasattr(engine, "set_spd_module") \
                    and str(getattr(engine, "spd_module", "") or "") != \
                    str(profile.get("spd_module") or ""):
                engine.set_spd_module(str(profile.get("spd_module") or ""))
                changed = True
            voice = profile.get("voice")
            if voice not in (None, "") and hasattr(engine, "set_voice"):
                at = _voice_index(engine, voice)
                if at is not None:
                    engine.set_voice(at)
                    changed = True
            for key, setter, base in (("rate", "set_rate", "Rate"),
                                      ("pitch", "set_pitch", "Pitch"),
                                      ("volume", "set_volume", "Volume")):
                value = profile.get(key)
                if value in (None, "", 0) or not hasattr(engine, setter):
                    continue
                own = self._settings.get_int("Speech", base,
                                             100 if key == "volume" else 0)
                if key == "volume":
                    wanted = max(0, min(100, int(own) + int(value) * 5))
                else:
                    wanted = max(-10, min(10, int(own) + int(value)))
                getattr(engine, setter)(wanted)
                changed = True
        except Exception as e:                       # noqa: BLE001
            print(f"[TitanAccess] class voice: {e}")
        return changed

    def _give_voice_back(self):
        """The reader's own engine, voice and dials again, from the
        settings - the one description of what the reader sounds like."""
        try:
            self._apply_own_voice()
        except Exception as e:                       # noqa: BLE001
            print(f"[TitanAccess] own voice back: {e}")

    def _render(self, item, eng):
        if item.segments:
            # **Parts whose class names a synthesizer of its own** - the
            # name in SAPI, the type in eSpeak - are grouped by profile and
            # each group rendered on its engine in turn, waited out between
            # groups; an interrupt between groups cuts what is left, as it
            # cuts anything queued. One utterance to the queue, several
            # clips to the ear.
            groups = self._groups(item.segments)
            if len(groups) > 1 or groups[0][0] is not None:
                for profile, parts in groups:
                    if self._superseded(item):
                        return
                    self._render_group(item, parts, profile)
                return
            # Preferred path: let the engine synthesize the pitched parts and
            # play them as ONE concatenated clip with a short silence between
            # them. Because the parts are joined before anything is heard, no
            # part can be cut off by the next one. ``StereoSpeech.speak_concat``
            # does this for every engine that can synthesize to memory (SAPI5,
            # eSpeak, say, and all TitanTTS plugin engines).
            done = False
            if hasattr(eng, "speak_concat"):
                try:
                    gap = max(self._SEGMENT_GAP_MS, int(
                        getattr(item, "gap_ms", 0) or 0))
                    done = bool(eng.speak_concat(item.segments, gap_ms=gap))
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
            # **Plain text goes the same way as the pitched parts**: rendered
            # to memory and played on Titan's own channel, where its end is
            # known exactly. Measured with the reader's own 32-bit SAPI voice
            # (the cross-bitness cscript bridge): a plain `speak_async` was
            # lost in the worker's switch to the bridge and the pacing then
            # waited eight seconds for audio that never started - the reader
            # mute and late - while the very next pitched announcement,
            # rendered through `speak_concat`, played at once. An engine that
            # cannot render to memory keeps `speak_async`.
            chunks = _speech_chunks(item.text)
            if len(chunks) > 1 and hasattr(eng, "speak_concat"):
                # **A long text is heard after its first sentence is
                # rendered, not the whole of it.** Rendered whole, a
                # paragraph was 88 ms (eSpeak) and 161 ms (SAPI) of silence
                # before its first word - measured; one sentence is a few.
                # Each chunk is played and waited out, so an interrupt
                # between two of them cuts the rest at once.
                import copy
                for chunk in chunks:
                    if self._superseded(item):
                        return
                    piece = copy.copy(item)
                    piece.text = chunk
                    try:
                        ok = bool(eng.speak_concat(
                            [(chunk, item.pitch, item.position)],
                            gap_ms=self._SEGMENT_GAP_MS))
                    except Exception as e:  # pragma: no cover
                        print(f"[TitanAccess] speak_concat (chunk) error: {e}")
                        ok = False
                    if not ok:
                        eng.speak_async(chunk, position=item.position,
                                        pitch_offset=item.pitch)
                    self._wait_for_playback(piece)
                return
            done = False
            if hasattr(eng, "speak_concat"):
                try:
                    done = bool(eng.speak_concat(
                        [(item.text, item.pitch, item.position)],
                        gap_ms=self._SEGMENT_GAP_MS))
                except Exception as e:  # pragma: no cover
                    print(f"[TitanAccess] speak_concat (plain) error: {e}")
                    done = False
            if not done:
                eng.speak_async(item.text, position=item.position,
                                pitch_offset=item.pitch)
        self._wait_for_playback(item)

    @staticmethod
    def _groups(segments):
        """``[(profile or None, [five-element segments])]`` - consecutive
        parts that share a voice profile, in order. The profile is the
        sixth element of a segment (`accessible.voice_profile_of`)."""
        groups = []
        for seg in segments:
            profile = None
            try:
                found = seg[5] if len(seg) > 5 else None
                if isinstance(found, dict) and found:
                    profile = dict(found)
            except Exception:                        # noqa: BLE001
                profile = None
            part = tuple(seg[:5])
            if groups and groups[-1][0] == profile:
                groups[-1][1].append(part)
            else:
                groups.append((profile, [part]))
        return groups

    def _voice_engine(self, profile):
        """The engine a part with a profile is rendered on.

        The reader's own private engine when it has one (the profile is
        borrowed onto it and the reader's voice put back after); otherwise
        a private engine of the reader's, never Titan's SHARED engine - a
        synthesizer switched under Titan's own applications mid-sentence
        is a bug in every one of them."""
        if getattr(self, "_own", False) and self._engine is not None:
            return self._engine
        try:
            from src.titan_core import tce_speech
            engine = tce_speech.get_private_reader_engine()
            if engine is not None:
                return engine
        except Exception:                            # noqa: BLE001
            pass
        return self._engine

    def _render_group(self, item, parts, profile):
        """One group of parts on one engine: the profile borrowed, the parts
        spoken as one clip, the clip waited out, the voice put back."""
        gap = max(self._SEGMENT_GAP_MS, int(getattr(item, "gap_ms", 0) or 0))
        if profile is None:
            engine = self._engine
            borrowed = False
        else:
            engine = self._voice_engine(profile)
            borrowed = self._borrow_on(engine, profile)
        try:
            done = False
            if hasattr(engine, "speak_concat"):
                try:
                    done = bool(engine.speak_concat(parts, gap_ms=gap))
                except Exception as e:  # pragma: no cover
                    print(f"[TitanAccess] speak_concat (group) error: {e}")
            if not done:
                text = ", ".join(str(p[0]) for p in parts if p and p[0])
                engine.speak_async(text, position=parts[0][2] if len(parts[0]) > 2 else 0.0,
                                   pitch_offset=0)
            self._wait_for_playback(item, engine)
        finally:
            if borrowed:
                self._give_voice_back_on(engine)

    def _borrow_on(self, engine, profile):
        """`_borrow_voice`, on a given engine."""
        kept = self._engine
        self._engine = engine
        try:
            return self._borrow_voice(profile)
        finally:
            self._engine = kept

    def _give_voice_back_on(self, engine):
        kept = self._engine
        self._engine = engine
        try:
            self._give_voice_back()
        finally:
            self._engine = kept

    def _wait_for_playback(self, item, engine=None):
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
        if engine is not None and engine is not self._engine:
            # The group's own engine is the one to ask whether it is
            # still speaking; the mixer's channel is the same for both.
            kept = self._engine
            self._engine = engine
            try:
                return self._wait_for_playback(item)
            finally:
                self._engine = kept
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
                if self.paused:
                    end_cap += 0.012
                    time.sleep(0.012)
                    continue
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
            if self.paused:
                t0 += 0.05
                time.sleep(0.05)
            else:
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
    def current_rate(self):
        """The rate the engine was last set to, or None where it cannot
        say - which is the honest answer, and what continuous reading
        needs before it may change the rate for a while."""
        eng = self._engine if self._mode == self._MODE_TCE else None
        if eng is None:
            return None
        value = getattr(eng, "_rate_setting", None)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

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

# --------------------------------------------------------------------------- #
# Module factory
# --------------------------------------------------------------------------- #
def get_speech(settings):
    """Build a :class:`SpeechAdapter` for the given settings store."""
    made = SpeechAdapter(settings)
    use(made)
    return made


# --------------------------------------------------------------------------- #
# The one that is really speaking
# --------------------------------------------------------------------------- #
#: The adapter the running reader is using. There is exactly one reader in
#: a process, and everything that wants to say something is not always
#: holding it: the modules shared with the NVDA add-on reach speech
#: through `portable/compat.py`, which is written against NVDA's own
#: `speech` module and has no engine to ask.
#:
#: **Without this they were silent.** `compat` called `speech_adapter.
#: speak(...)`, which did not exist, inside a bare `except` - so every one
#: of the ported features said nothing at all in this reader while
#: working perfectly in NVDA, and nothing anywhere said why.
_current = None


def _shut_sapi_worker(engine):
    worker = getattr(engine, '_sapi_worker', None)
    if worker is None:
        return
    try:
        engine._sapi_worker = None
        worker._cmd_queue.put(None)
        thread = getattr(worker, '_thread', None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
    except Exception:                                # noqa: BLE001
        pass
    process = getattr(worker, '_subprocess_process', None)
    if process is not None:
        try:
            if process.poll() is None:
                process.kill()
        except Exception:                            # noqa: BLE001
            pass


def _titan_speaks_on_its_own(private):
    """Whether Titan's own speech has an engine that is not the reader's -
    in which case the shared Titan TTS bridges are Titan's to keep."""
    try:
        from src.titan_core import stereo_speech
        shared = getattr(stereo_speech, '_stereo_speech_instance', None)
        if shared is not None and shared is not private:
            return True
    except Exception:                                # noqa: BLE001
        pass
    try:
        from src.titan_core import tce_speech
        for name in ('_speaker', '_reader_speaker'):
            other = getattr(tce_speech, name, None)
            if other is not None and other is not private and \
                    type(other).__name__ == 'StereoSpeech':
                return True
    except Exception:                                # noqa: BLE001
        pass
    return False


def _shut_bridges():
    """Every Titan TTS engine of the shared registry shut down, and the
    registry forgotten so the next start loads it again."""
    try:
        from src.titan_core import stereo_speech
        registry = getattr(stereo_speech, '_engine_registry', None)
    except Exception:                                # noqa: BLE001
        return 0
    if registry is None:
        return 0
    closed = 0
    for engine in list(getattr(registry, '_engines', {}).values()):
        shutdown = getattr(engine, 'shutdown', None)
        if callable(shutdown):
            try:
                shutdown()
                closed += 1
            except Exception:                        # noqa: BLE001
                pass
    try:
        stereo_speech._engine_registry = None
        from src.tts import engine_registry
        if getattr(engine_registry, '_registry', None) is registry:
            engine_registry._registry = None
    except Exception:                                # noqa: BLE001
        pass
    return closed


def release_private_engine(engine):
    """The reader's private ``StereoSpeech`` taken down (see
    :meth:`SpeechAdapter.shutdown`). Written here rather than in
    ``tce_speech`` because a compiled Titan has that module frozen into
    Titan.exe and this component must not need a rebuild."""
    try:
        from src.titan_core import tce_speech
        if getattr(tce_speech, '_private_reader_speaker', None) is engine:
            tce_speech._private_reader_speaker = None
    except Exception:                                # noqa: BLE001
        pass
    if engine is None:
        return
    try:
        engine.stop()
    except Exception:                                # noqa: BLE001
        pass
    _shut_sapi_worker(engine)
    if not _titan_speaks_on_its_own(engine):
        closed = _shut_bridges()
        if closed:
            print(f"[TitanAccess] {closed} Titan TTS bridge(s) shut down "
                  "with the reader")


def use(adapter):
    """Remember the adapter the reader is speaking through."""
    global _current
    _current = adapter
    return adapter


def current():
    """The adapter that is really speaking, or None."""
    return _current


#: A text longer than this is spoken a sentence group at a time.
CHUNK_FROM = 240
#: A chunk after the first gathers sentences up to about this long.
CHUNK_SIZE = 160

_SENTENCE_END = None


def _speech_chunks(text):
    """``text`` cut where its sentences end: the first sentence alone (it
    is what has to be heard soonest), then groups of about `CHUNK_SIZE`.
    A text short enough, or with no sentence ends, is one chunk."""
    global _SENTENCE_END
    text = str(text or '')
    if len(text) <= CHUNK_FROM:
        return [text]
    if _SENTENCE_END is None:
        import re
        _SENTENCE_END = re.compile(r'(?<=[.!?\u2026;:])\s+')
    sentences = [one for one in _SENTENCE_END.split(text) if one.strip()]
    if len(sentences) < 2:
        return [text]
    chunks = [sentences[0]]
    current = ''
    for one in sentences[1:]:
        current = (current + ' ' + one).strip() if current else one
        if len(current) >= CHUNK_SIZE:
            chunks.append(current)
            current = ''
    if current:
        chunks.append(current)
    return chunks


def speak(text, position=0.0, interrupt=True, pitch_offset=0, voice=None):
    """Say one thing through the reader's own voice. ``True`` if it went.

    Answers False rather than raising when there is no reader speaking
    yet - which is a real moment, at start-up and after a teardown, and
    not one anything should stop for.
    """
    adapter = _current
    if adapter is None:
        return False
    try:
        adapter.speak(str(text or ""), position=position,
                      interrupt=interrupt, pitch_offset=pitch_offset,
                      voice=voice)
        return True
    except Exception:                                # noqa: BLE001
        return False


def speak_in_class(text, tag, interrupt=False):
    """Say one whole thing in a voice CLASS - a notification, what another
    program said, an alert - the way the class manager set it up.

    The shared `classes` store is the same file the NVDA add-on's manager
    edits, and this reader read only its dials for the parts of a control;
    a whole-utterance class naming a synthesizer and a voice of its own was
    stored and never spoken. Now the utterance goes to that synthesizer in
    that voice, with the class's dials on top of the reader's own, and the
    reader's own voice is put back afterwards. ``True`` when it was said.
    """
    profile = {}
    try:
        from .portable import classes
        profile = dict(classes.voice_of(tag) or {})
        if not classes.may_name_synth(tag):
            # A class that may not name a synthesizer still has its voice
            # and variant OF the reader's synthesizer (`_resolve`).
            profile.pop("synth", None)
    except Exception:                                # noqa: BLE001
        profile = {}
    return speak(text, interrupt=interrupt,
                 pitch_offset=int(profile.get("pitch") or 0),
                 voice=profile if any(profile.get(k) for k in
                                      ("synth", "voice", "variant", "rate",
                                       "volume"))
                 else None)


def _external_profile(profile):
    """The external synthesizer a voice profile names, or ''."""
    try:
        synth = str((profile or {}).get("synth") or "")
    except Exception:                                # noqa: BLE001
        return ""
    return synth if synth.startswith("nvda:") else ""


def speak_with(profile, text, interrupt=True):
    """Say ``text`` with a whole voice profile as it stands on a dialog -
    what the class manager's Try button asks, so a change is heard before
    it is kept."""
    profile = dict(profile or {})
    return speak(text, interrupt=interrupt,
                 pitch_offset=int(profile.get("pitch") or 0), voice=profile)


def _voice_index(engine, voice):
    """Where ``voice`` is in the engine's own list - by id, display name or
    name for a dict, by text for a string, by number for an index. None
    when it is nowhere, so a voice this engine has not got changes
    nothing rather than choosing its first."""
    if voice in (None, ""):
        return None
    try:
        voices = engine.get_available_voices() or []
    except Exception:                                # noqa: BLE001
        voices = []
    wanted = str(voice).strip()
    for at, one in enumerate(voices):
        if isinstance(one, dict):
            if wanted in (str(one.get("id")), str(one.get("display_name")),
                          str(one.get("name"))):
                return at
        elif str(one).strip() == wanted:
            return at
    try:
        number = int(wanted)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number < len(voices) else None


def speak_segments(segments):
    """The parts at their own pitches - a name, what it is, its state."""
    adapter = _current
    if adapter is None:
        return False
    try:
        adapter.speak_segments(segments)
        return True
    except Exception:                                # noqa: BLE001
        return False


def stop():
    """Stop the reader speaking. ``True`` if there was one."""
    adapter = _current
    if adapter is None:
        return False
    try:
        adapter.stop()
        return True
    except Exception:                                # noqa: BLE001
        return False
