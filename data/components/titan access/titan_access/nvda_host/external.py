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


#: What the reader asked of each synthesizer - its voice, variant and
#: levels - and the instance it was last put on. **The choice belongs to the
#: synthesizer, not to one instance of it**: an instance is retired when it
#: stalls, or when looking at other synthesizers' voices pushes it out of
#: `nvda_host.KEEP_RUNNING`, and the next word made a NEW one - on its
#: default voice. Reported as "I chose an external synthesizer's voice and it
#: speaks in some default one straight away" (Cerence: Krzysztof chosen,
#: Ewa heard after the instance was made again). Every new instance is
#: dressed in what was asked before it says a word.
_wanted = {}
_dressed = {}


def _synth(synth_id):
    from titan_access import nvda_host
    synth = nvda_host.synth_instance(str(synth_id)[len(PREFIX):])
    _hook(synth)
    if _dressed.get(synth_id) is not synth:
        _dressed[synth_id] = synth
        _dress(synth_id, synth)
    return synth


def _dress(synth_id, synth):
    """Put the remembered voice, then variant, then levels on ``synth``."""
    asked = dict(_wanted.get(synth_id) or {})
    if asked.get('voice'):
        _put_voice(synth, asked['voice'])
    if asked.get('variant'):
        _put_variant(synth, asked['variant'])
    for name in ('rate', 'pitch', 'volume'):
        if asked.get(name) is not None:
            try:
                setattr(synth, name, max(0, min(100, int(asked[name]))))
            except Exception:                        # noqa: BLE001
                pass


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


_ssml_cache = {}


def _parts_apart(synth):
    """Whether the parts of an announcement must be said as SEPARATE
    utterances for the pause between them to be a pause: a synthesizer
    with no ``BreakCommand`` that turns NVDA's sequence into SSML through
    a subclass of NVDA's own converter - RHVoice.

    RHVoice is why. It reports an index from inside the player, and its
    library reports a mark before the vocoder has finished the word in
    front of it, so a pause put in at that index landed INSIDE the word:
    "Zapisz" was heard as "Zapi", a pause, "sz" (measured on Natan: the
    second syllable split 140 + 50 ms around the silence). Handed a
    ``<break time="250ms"/>`` instead, its library made no silence at all
    - a run of clicks, the longest quiet stretch under 150 ms. Said one
    part at a time, each word is whole and the pause is the one asked
    for."""
    cls = type(synth)
    if cls in _ssml_cache:
        return _ssml_cache[cls]
    found = False
    try:
        import sys
        from .shims import speechXml
        module = sys.modules.get(cls.__module__)
        for value in vars(module).values() if module is not None else ():
            if isinstance(value, type) and \
                    issubclass(value, speechXml.SsmlConverter) and \
                    value is not speechXml.SsmlConverter and \
                    getattr(value, 'convertBreakCommand', None) is \
                    speechXml.SsmlConverter.convertBreakCommand:
                found = True
                break
    except Exception:                                # noqa: BLE001
        found = False
    _ssml_cache[cls] = found
    return found


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
                paused=None, _warm=False, _lead_ms=0):
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
    if gap_ms and not native_breaks and (not has_index or
                                         _parts_apart(synth)):
        # **A synthesizer that has no breaks and no indexes still gets its
        # pauses**: the parts are said one after another. The next part is
        # asked for at once, and the player puts in front of its first
        # sound whatever of the pause the synthesizer has not already
        # spent starting (`nvwave.begin_utterance`) - so the pause is the
        # one asked for, not that plus the synthesizer's start-up.
        for at, part in enumerate(spoken):
            if cancelled is not None and cancelled():
                return False
            if not speak_parts(synth_id, [part], cancelled, timeout, 0,
                               paused, _lead_ms=gap_ms if at else 0):
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
    nvwave.begin_utterance(trim=loud_enough, pause_ms=_lead_ms)
    synth.speak(sequence)
    with _LOCK:
        _state['spoken'] += 1
    deadline = time.time() + timeout
    # **A synthesizer that has stopped answering is noticed, not waited
    # out.** Its host process gone, its library wedged: nothing is ever fed,
    # no index ever comes, and every utterance used to wait its whole
    # minute - a reader that had gone silent, from the outside a reader
    # that had hung. No sound at all within `FIRST_SOUND_S` gives up, and
    # the instance is made again for the next word (`_stalled`).
    silent_until = time.time() + FIRST_SOUND_S
    with _WAKE:
        while time.time() < deadline:
            if time.time() > silent_until and \
                    nvwave.fed_bytes[0] == start_fed and \
                    index not in _state['reached'] and \
                    _state['done_seq'] == start_seq and \
                    not (paused is not None and paused()):
                _state['reached'].pop(index, None)
                _WAKE.release()
                try:
                    _stalled(synth_id, synth)
                finally:
                    _WAKE.acquire()
                return False
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
                silent_until += TICK
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


#: How long a synthesizer may take to produce its first sound before it is
#: taken for one that has stopped answering. Samsung's host takes two
#: seconds to start the first time, which the warm-up absorbs; this is
#: well beyond any synthesizer that is working.
FIRST_SOUND_S = 6.0


def _stalled(synth_id, synth):
    """A synthesizer that made no sound: stopped, retired and counted, so
    the next utterance gets a fresh instance rather than the same silence."""
    with _LOCK:
        _state['stalled'] = _state.get('stalled', 0) + 1
    try:
        from titan_access.log import log
        log('[TitanAccess] external synthesis: %s made no sound in %.0f s '
            '- starting it again' % (synth_id, FIRST_SOUND_S))
    except Exception:                                # noqa: BLE001
        pass
    try:
        synth.cancel()
    except BaseException:                            # noqa: BLE001
        pass
    try:
        from titan_access import nvda_host
        nvda_host.retire_synth(str(synth_id)[len(PREFIX):])
    except Exception:                                # noqa: BLE001
        pass


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


def _voice_id(synth, voice):
    """The synthesizer's own id for ``voice``: the id itself, or the voice
    named by its display name (what a settings file written by hand or by
    an older Titan Access may hold), case aside. '' for none."""
    voice = str(voice or '')
    try:
        found = synth.availableVoices or {}
    except Exception:                                # noqa: BLE001
        return voice
    if voice in found:
        return voice
    low = voice.lower()
    for key, value in found.items():
        if str(key).lower() == low or \
                str(getattr(value, 'displayName', '')).lower() == low:
            return key
    return ''


def _put_voice(synth, voice):
    key = _voice_id(synth, voice)
    if not key:
        return False
    try:
        if str(synth.voice or '') != str(key):
            synth.voice = key
        return True
    except Exception:                                # noqa: BLE001
        return False


def set_voice(synth_id, voice):
    """Put ``voice`` on the synthesizer and remember it, so an instance made
    later is given it too. True when it is in force."""
    voice = str(voice or '')
    if not voice:
        return False
    _wanted.setdefault(synth_id, {})['voice'] = voice
    try:
        synth = _synth(synth_id)
    except Exception:                                # noqa: BLE001
        return False
    if _put_voice(synth, voice):
        return True
    try:
        from titan_access.log import log
        log('[TitanAccess] external synthesis: %s has no voice %r'
            % (synth_id, voice))
    except Exception:                                # noqa: BLE001
        pass
    return False


def _supports_setting(synth, name):
    try:
        if hasattr(synth, 'isSupported'):
            return bool(synth.isSupported(name))
    except Exception:                                # noqa: BLE001
        pass
    return any(getattr(one, 'id', None) == name for one in
               getattr(synth, 'supportedSettings', ()) or ())


def _rows(found):
    rows = []
    for key, value in (found or {}).items():
        label = getattr(value, 'displayName', None) or key
        rows.append((str(key), str(label)))
    return rows


def variants(synth_id, voice=None):
    """``[(id, name)]`` of an external synthesizer's VARIANTS - for Cerence
    the quality a voice is installed in (compact, embedded-pro,
    embedded-high), for eSpeak its variants. Empty when the synthesizer
    has no variant setting.

    The variants belong to a VOICE, so ``voice`` (when it is not the one
    the synthesizer has now) is put on just long enough to ask and taken
    off again; the driver forgets its own list both times, as it does when
    NVDA changes the voice."""
    try:
        synth = _synth(synth_id)
    except Exception:                                # noqa: BLE001
        return []
    if not _supports_setting(synth, 'variant'):
        return []
    with _LOCK:
        try:
            now = synth.voice
        except Exception:                            # noqa: BLE001
            now = None
        switched = bool(voice) and str(voice) != str(now or '')
        try:
            if switched:
                synth.voice = voice
            if hasattr(synth, '_availableVariants'):
                del synth._availableVariants
            return _rows(synth.availableVariants)
        except BaseException:                        # noqa: BLE001
            return []
        finally:
            if switched and now:
                try:
                    synth.voice = now
                    if hasattr(synth, '_availableVariants'):
                        del synth._availableVariants
                except BaseException:                # noqa: BLE001
                    pass


def variant(synth_id):
    try:
        return str(_synth(synth_id).variant or '')
    except BaseException:                            # noqa: BLE001
        return ''


def set_variant(synth_id, wanted):
    """Put ``wanted`` on the synthesizer, if it is one of its variants
    (Cerence refuses anything else in silence, and so would the user's
    log). True when it is in force."""
    wanted = str(wanted or '')
    if not wanted:
        return False
    _wanted.setdefault(synth_id, {})['variant'] = wanted
    try:
        return _put_variant(_synth(synth_id), wanted)
    except BaseException:                            # noqa: BLE001
        return False


def _put_variant(synth, wanted):
    try:
        if not _supports_setting(synth, 'variant'):
            return False
        if wanted not in [key for key, _l in _rows(synth.availableVariants)]:
            return False
        if str(synth.variant or '') != wanted:
            synth.variant = wanted
        return True
    except BaseException:                            # noqa: BLE001
        return False


def set_levels(synth_id, rate=None, pitch=None, volume=None):
    """The reader's levels on NVDA's 0-100 scale."""
    asked = _wanted.setdefault(synth_id, {})
    for name, value in (('rate', rate), ('pitch', pitch), ('volume', volume)):
        if value is not None:
            asked[name] = value
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
                'stalled': _state.get('stalled', 0),
                'index_when_played': sorted(_state['on_play'])}
