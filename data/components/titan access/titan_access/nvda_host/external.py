# -*- coding: utf-8 -*-
"""External synthesis: the reader speaking through an NVDA synthesizer.

A subsystem of Titan Access - chosen in the reader's speech system dialog
as "External synthesizers (NVDA add-ons)" - and nothing to do with
Titan's own TTS engines. The synthesizer is given an NVDA speech sequence
(text, a pitch change, an index at the end) and the reader waits for that
index, or for the synthesizer to say it is done, before the next
utterance; Stop cancels it."""

import threading
import time

_LOCK = threading.RLock()
_WAKE = threading.Condition(_LOCK)
_state = {'index': 1000, 'reached': {}, 'done_seq': 0, 'hooked': None,
          'spoken': 0, 'gaps': {}, 'on_play': set(), 'injected': 0,
          'why': ''}

PREFIX = 'nvda:'

#: How often the wait looks at the cancel and pause switches. A key the
#: user presses stops the voice within this.
TICK = 0.01


def is_external(synth_id):
    return str(synth_id or '').startswith(PREFIX)


def _synth(synth_id):
    from titan_access import nvda_host
    synth = nvda_host.synth_instance(str(synth_id)[len(PREFIX):])
    _hook(synth)
    return synth


def _name_of(synth):
    return str(getattr(synth, 'name', '') or type(synth).__name__)


def _hook(synth):
    with _LOCK:
        if _state['hooked'] is synth:
            return
        first = _state['hooked'] is None
        _state['hooked'] = synth
    if not first:
        return
    from .shims import synthDriverHandler
    from .shims import nvwave

    def reached(synth=None, index=None, **_kwargs):
        with _LOCK:
            gap = _state['gaps'].pop(index, None)
        if gap:
            # **A pause the synthesizer has no command for** (Samsung,
            # RHVoice). Its index between the two parts arrives here. A
            # synthesizer that reports an index as it MAKES the audio
            # (Samsung) has fed the first part and not the second, so the
            # silence goes after what is fed; one that reports it as the
            # audio is PLAYED (RHVoice, inside a player's onDone) is
            # exactly where the playing has got to, so the silence goes in
            # front of what is still waiting. Either way the padding the
            # synthesizer put there itself is cut first, so the pause is
            # the pause the reader asked for.
            player = nvwave.last_player()
            if player is not None:
                when_played = nvwave.in_index_callback()
                player.insert_silence(gap, now=when_played)
                with _LOCK:
                    _state['injected'] += 1
                    if when_played:
                        _state['on_play'].add(_name_of(synth))
            return
        if index is not None and not nvwave.in_index_callback():
            # The end of the utterance, reported as it was made: what the
            # synthesizer padded it with need not be waited out.
            player = nvwave.last_player()
            if player is not None:
                player.trim_tail()
        with _WAKE:
            _state['reached'][index] = _state['done_seq']
            _WAKE.notify_all()

    def done(synth=None, **_kwargs):
        with _WAKE:
            _state['done_seq'] += 1
            _WAKE.notify_all()
    synthDriverHandler.synthIndexReached.register(reached)
    synthDriverHandler.synthDoneSpeaking.register(done)
    _state['handlers'] = (reached, done)          # kept alive


def _supports(synth, name):
    return name in [getattr(c, '__name__', '') for c in
                    getattr(synth, 'supportedCommands', ()) or ()]


def speak(synth_id, text, pitch_offset=0, cancelled=None, timeout=60.0):
    """Say ``text`` and return when it has been said (or cancelled)."""
    return speak_parts(synth_id, [(text, pitch_offset)], cancelled, timeout)


def _wait_gap(gap_ms, cancelled):
    deadline = time.time() + gap_ms / 1000.0
    while time.time() < deadline:
        if cancelled is not None and cancelled():
            return False
        time.sleep(TICK)
    return True


def speak_parts(synth_id, parts, cancelled=None, timeout=60.0, gap_ms=0,
                paused=None, _warm=False):
    """Say ``[(text, pitch offset -10..10)]`` as ONE NVDA sequence - each
    part at its own pitch, as the reader says a control's name, type and
    state, with ``gap_ms`` of silence between them - and return when it
    has been HEARD (or cancelled).

    **Heard, not made.** Cerence and Samsung report an index when they
    have synthesised up to it, which is the moment NVDA needs for its own
    bookkeeping and long before anybody hears it; waiting only for the
    index returned the utterance in a few milliseconds and the next one
    was queued behind it in the player, so the reader fell further and
    further behind the keyboard. The final index is waited for AND then
    either the synthesizer's "done speaking" or every player having
    played what it was fed - whichever comes first."""
    from .shims.speech import commands
    from .shims import nvwave
    if not _warm:
        _warming.wait(8.0)
    synth = _synth(synth_id)
    spoken = [(str(text or '').strip(), pitch) for text, pitch in parts
              if str(text or '').strip()]
    if not spoken:
        return True
    has_index = _supports(synth, 'IndexCommand')
    native_breaks = _supports(synth, 'BreakCommand')
    gap_ms = int(gap_ms or 0) if len(spoken) > 1 else 0
    if gap_ms and not native_breaks and not has_index:
        # **A synthesizer that has no breaks and no indexes still gets its
        # pauses**: the parts are said
        # one after another, and the gap is kept here.
        for at, part in enumerate(spoken):
            if at and not _wait_gap(gap_ms, cancelled):
                return False
            if not speak_parts(synth_id, [part], cancelled, timeout, 0,
                               paused):
                return False
        return True
    sequence = []
    with _LOCK:
        for text, pitch in spoken:
            if sequence and gap_ms:
                if native_breaks:
                    # NVDA's own BreakCommand: real silence from the synth.
                    sequence.append(commands.BreakCommand(gap_ms))
                else:
                    _state['index'] += 1
                    _state['gaps'][_state['index']] = gap_ms
                    sequence.append(commands.IndexCommand(_state['index']))
            sequence.append(commands.PitchCommand(offset=int(pitch or 0) * 5))
            sequence.append(text)
        sequence.append(commands.PitchCommand())
        _state['index'] += 1
        index = _state['index']
        sequence.append(commands.IndexCommand(index))
        start_seq = _state['done_seq']
        start_fed = nvwave.fed_bytes[0]
    try:
        loud_enough = int(getattr(synth, 'volume', 100) or 0) >= 20
    except Exception:                                # noqa: BLE001
        loud_enough = True
    nvwave.begin_utterance(trim=loud_enough)
    synth.speak(sequence)
    with _LOCK:
        _state['spoken'] += 1
    deadline = time.time() + timeout
    with _WAKE:
        while time.time() < deadline:
            if cancelled is not None and cancelled():
                _state['reached'].pop(index, None)
                _WAKE.release()
                try:
                    stop(synth_id)
                finally:
                    _WAKE.acquire()
                return False
            if paused is not None and paused():
                # Paused speech is not late speech: the wait holds.
                deadline += TICK
                _WAKE.wait(TICK)
                continue
            if has_index and index in _state['reached']:
                if _state['done_seq'] > _state['reached'][index] or \
                        nvwave.drained():
                    del _state['reached'][index]
                    return True
            elif not has_index:
                # A synthesizer with no indexes: done is done, and a
                # player that has played everything it was given is too.
                if _state['done_seq'] > start_seq or (
                        nvwave.fed_bytes[0] > start_fed and
                        nvwave.drained()):
                    return True
            _WAKE.wait(TICK)
    with _LOCK:
        _state['reached'].pop(index, None)
    return False


_warming = threading.Event()
_warming.set()
_warmed = set()


def warm(synth_id):
    """Start what a synthesizer starts on its first word - Samsung's host
    process is two seconds of it, RHVoice's voice a few tenths - before
    the reader needs a word. One short word is said with every player
    MUTED (`nvwave.muted`): the synthesizer does all of its first-time
    work and nothing is heard. A real utterance that arrives meanwhile
    waits for it (`speak_parts`), which costs it nothing it would not
    have paid anyway."""
    with _LOCK:
        if not _warming.is_set() or synth_id in _warmed:
            # Once per synthesizer: every settings apply calls this, and a
            # second warm-up is a real utterance's wait for nothing.
            return
        _warmed.add(synth_id)
        _warming.clear()

    def run():
        from .shims import nvwave
        try:
            _synth(synth_id)                 # made (and marked cold) first
            with _LOCK:
                _warmed.add(synth_id)
            with nvwave.muted():
                speak_parts(synth_id, [('a', 0)], timeout=6.0, _warm=True)
        except Exception:                            # noqa: BLE001
            pass
        finally:
            _warming.set()
    threading.Thread(target=run, name='TitanAccessWarmSynth',
                     daemon=True).start()


def stop(synth_id):
    try:
        _synth(synth_id).cancel()
    except Exception:                                # noqa: BLE001
        pass


def pause(synth_id, switch):
    """NVDA's own pause: the synthesizer holds where it is, and goes on
    from there when it is unpaused."""
    try:
        _synth(synth_id).pause(bool(switch))
        return True
    except Exception:                                # noqa: BLE001
        return False


def voices(synth_id):
    """``[(id, name)]`` of an external synthesizer."""
    try:
        found = _synth(synth_id).availableVoices
    except Exception:                                # noqa: BLE001
        return []
    return [(key, getattr(value, 'displayName', key))
            for key, value in (found or {}).items()]


def set_voice(synth_id, voice):
    try:
        _synth(synth_id).voice = voice
        return True
    except Exception:                                # noqa: BLE001
        return False


def set_levels(synth_id, rate=None, pitch=None, volume=None):
    """The reader's levels on NVDA's 0-100 scale."""
    synth = _synth(synth_id)
    for name, value in (('rate', rate), ('pitch', pitch),
                        ('volume', volume)):
        if value is None:
            continue
        try:
            setattr(synth, name, max(0, min(100, int(value))))
        except Exception:                            # noqa: BLE001
            pass


def report():
    with _LOCK:
        return {'spoken': _state['spoken'], 'index': _state['index'],
                'silences_inserted': _state['injected'],
                'index_when_played': sorted(_state['on_play'])}
