# -*- coding: utf-8 -*-
"""NVDA's `nvwave`: where a synthesizer's PCM goes.

`WavePlayer.feed(data, onDone=...)` streams to the sound device through
`sounddevice` (PortAudio - Windows, Linux and macOS alike), and every
``onDone`` is called when the audio fed before it has really been PLAYED,
which is what a synthesizer's index callbacks mean: NVDA's speech knows
where it has got to from them, and so does Titan Access."""

import os
import threading
import time

from enum import Enum

from . import extensionPoints

decide_playWaveFile = extensionPoints.Decider()

_players = []
_LOCK = threading.RLock()

#: ``TITAN_ACCESS_SILENT_AUDIO=1``: nothing reaches a sound device, every
#: callback still comes, and the bytes are counted - how a test makes a
#: real synthesizer speak without speaking out loud.
fed_bytes = [0]

#: The player most recently fed audio - where a pause the synthesizer
#: cannot make itself is put (`insert_silence`).
_last = [None]

_here = threading.local()


def in_index_callback():
    """Whether this thread is running an ``onDone`` callback right now -
    which tells a synthesizer that reports an index when its audio is
    PLAYED from one that reports it when the audio is MADE."""
    return bool(getattr(_here, 'callback', False))


def last_player():
    return _last[0]


def drained():
    """Whether every open player has played everything fed to it."""
    with _LOCK:
        players = list(_players)
    for player in players:
        if player._closed:
            continue
        with player._lock:
            if player._buffer or player._marks:
                return False
    return True


#: Below this a 16-bit sample is silence (about -40 dB). What a
#: synthesizer pads its speech with - Samsung's 0.65 s after every part,
#: Cerence's tenth of a second before - is cut, as NVDA cuts the leading
#: silence itself: the reader is heard sooner and a pause is the pause.
QUIET = 300

#: What is kept of the silence cut at either end, so a word is not
#: clipped on its first or last sample.
KEEP_MS = 10

#: At most this much is cut in front of an utterance. A voice set so
#: quiet that its speech is below `QUIET` would otherwise be cut away
#: whole; past this the rest is kept as it came.
MAX_HEAD_MS = 400


def _quiet_head(data, frame):
    """How many bytes at the start of ``data`` are silence (whole frames)."""
    import array
    usable = len(data) - len(data) % frame
    samples = array.array('h', bytes(data[:usable]))
    for at, value in enumerate(samples):
        if value > QUIET or value < -QUIET:
            return (at * 2) - (at * 2) % frame
    return usable


def _quiet_tail(data, frame):
    """How many bytes at the end of ``data`` are silence (whole frames)."""
    import array
    usable = len(data) - len(data) % frame
    samples = array.array('h', bytes(data[:usable]))
    count = len(samples)
    for back in range(count - 1, -1, -1):
        value = samples[back]
        if value > QUIET or value < -QUIET:
            loud_end = (back + 1) * 2
            loud_end += (-loud_end) % frame
            return usable - loud_end
    return usable


_mute = [0]
_trimming = [True]


class muted(object):
    """While inside, nothing fed reaches a sound device (the callbacks
    still come) - a synthesizer warmed up without a sound."""

    def __enter__(self):
        with _LOCK:
            _mute[0] += 1
        return self

    def __exit__(self, *_exc):
        with _LOCK:
            _mute[0] -= 1
        return False


def begin_utterance(trim=True):
    """A new utterance is about to be fed: each player cuts the silence
    in front of its first sound (unless ``trim`` is False - a voice turned
    so far down that its speech could be taken for silence)."""
    with _LOCK:
        players = list(_players)
        _trimming[0] = bool(trim)
    for player in players:
        player._trim_head = bool(trim)
        player._head_cut = 0


def _stream_settings():
    """How a stream is opened, best first: WASAPI's shared mode at low
    latency (what NVDA itself uses - MME adds a tenth of a second or more
    before the first word), then the default device at low latency."""
    found = []
    try:
        import sounddevice
        for at, api in enumerate(sounddevice.query_hostapis()):
            if 'WASAPI' in str(api.get('name', '')) and \
                    api.get('default_output_device', -1) >= 0:
                extra = None
                try:
                    extra = sounddevice.WasapiSettings(auto_convert=True)
                except TypeError:
                    try:
                        extra = sounddevice.WasapiSettings()
                    except Exception:                # noqa: BLE001
                        extra = None
                found.append({'device': api['default_output_device'],
                              'latency': 'low', 'extra_settings': extra})
    except Exception:                                # noqa: BLE001
        pass
    found.append({'latency': 'low'})
    found.append({})
    return found


def _silent():
    return os.environ.get('TITAN_ACCESS_SILENT_AUDIO') == '1'


class AudioPurpose(Enum):
    SPEECH = 1
    SOUNDS = 2


def getOutputDeviceNames():
    try:
        import sounddevice
        return [one['name'] for one in sounddevice.query_devices()
                if one.get('max_output_channels', 0) > 0]
    except Exception:                                # noqa: BLE001
        return []


def outputDeviceNameToID(name, useDefaultIfInvalid=False):
    return None


class WavePlayer(object):
    """A PCM stream. Fed bytes are queued and played in order."""

    def __init__(self, channels, samplesPerSec, bitsPerSample,
                 outputDevice=None, closeWhenIdle=False, wantDucking=True,
                 buffered=False, purpose=AudioPurpose.SPEECH):
        self.channels = int(channels)
        self.samplesPerSec = int(samplesPerSec)
        self.bitsPerSample = int(bitsPerSample)
        self._lock = threading.Condition()
        self._buffer = bytearray()
        self._consumed = 0            # bytes ever played
        self._fed = 0                 # bytes ever fed
        self._marks = []              # [(end offset, callback)]
        self._stream = None
        self._paused = False
        self._closed = False
        self._trim_head = False
        self._head_cut = 0
        with _LOCK:
            _players.append(self)

    # -- the device -------------------------------------------------- #
    def _open(self):
        if self._stream is not None:
            return True
        try:
            import sounddevice
        except Exception:                            # noqa: BLE001
            return False
        dtype = {8: 'uint8', 16: 'int16', 24: 'int24',
                 32: 'int32'}.get(self.bitsPerSample, 'int16')
        frame = self.channels * self.bitsPerSample // 8

        def callback(outdata, frames, timing, status):
            wanted = frames * frame
            with self._lock:
                if self._paused:
                    chunk = b''
                else:
                    chunk = bytes(self._buffer[:wanted])
                    del self._buffer[:len(chunk)]
                    self._consumed += len(chunk)
                due = [mark for mark in self._marks
                       if mark[0] <= self._consumed]
                self._marks = [mark for mark in self._marks
                               if mark[0] > self._consumed]
                self._lock.notify_all()
            outdata[:len(chunk)] = chunk
            if len(chunk) < wanted:
                outdata[len(chunk):] = b'\x00' * (wanted - len(chunk))
            if due:
                threading.Thread(target=_all_safely,
                                 args=([done for _end, done in due],),
                                 daemon=True).start()

        for settings in _stream_settings():
            settings = {key: value for key, value in settings.items()
                        if value is not None}
            try:
                stream = sounddevice.RawOutputStream(
                    samplerate=self.samplesPerSec, channels=self.channels,
                    dtype=dtype, callback=callback, blocksize=0,
                    **settings)
                stream.start()
            except Exception:                        # noqa: BLE001
                continue
            self._stream = stream
            return True
        self._stream = None
        return False

    # -- NVDA's interface ---------------------------------------------- #
    def feed(self, data, size=None, onDone=None):
        if self._closed:
            return
        if data is not None and not isinstance(data, (bytes, bytearray)):
            try:
                import ctypes
                data = ctypes.string_at(data, size) if size \
                    else bytes(data)
            except Exception:                        # noqa: BLE001
                data = bytes(data)
        if data is not None and size is not None:
            data = bytes(data)[:size]
        if data:
            fed_bytes[0] += len(data)
        if data and self._trim_head and self.bitsPerSample == 16:
            frame = self.channels * 2
            room = int(self.samplesPerSec * MAX_HEAD_MS / 1000) * frame \
                - self._head_cut
            cut = min(_quiet_head(data, frame), max(0, room))
            if cut >= len(data) - len(data) % frame:
                self._head_cut += cut
                data = b''                   # all of it silence: wait on
            else:
                keep = int(self.samplesPerSec * KEEP_MS / 1000) * frame \
                    if cut < room else 0
                data = bytes(data[max(0, cut - keep):])
                self._trim_head = False
        with self._lock:
            if data:
                self._buffer.extend(data)
                self._fed += len(data)
                _last[0] = self
            if onDone is not None:
                self._marks.append((self._fed, onDone))
        if _silent() or not self._open() or _mute[0]:
            # No device: the callbacks must still come, or the synth waits
            # for ever for an index that is never reached.
            with self._lock:
                marks, self._marks = self._marks, []
                self._buffer.clear()
                self._consumed = self._fed
                self._lock.notify_all()
            _all_safely([done for _end, done in marks])

    def trim_tail(self):
        """Cut the silence at the end of what is fed and not yet played."""
        if self.bitsPerSample != 16 or not _trimming[0]:
            return 0
        frame = self.channels * 2
        keep = int(self.samplesPerSec * KEEP_MS / 1000) * frame
        with self._lock:
            quiet = _quiet_tail(self._buffer, frame)
            if quiet >= len(self._buffer) - len(self._buffer) % frame:
                # Nothing loud in it: a voice turned right down, not
                # padding - left as it is.
                return 0
            cut = quiet - keep
            if cut <= 0:
                return 0
            del self._buffer[len(self._buffer) - cut:]
            self._fed -= cut
            self._marks = [(min(end, self._fed), done)
                           for end, done in self._marks]
            return cut

    def insert_silence(self, ms, now=False):
        """``ms`` of silence - a pause the synthesizer has no command for.

        After what has been fed so far (``now=False``: the synthesizer
        reported where the parts meet as it MADE the audio), or in front
        of what is still waiting to be played (``now=True``: it reported
        it as the audio was PLAYED, so the meeting point is where the
        playing has just got to; the silence the next part starts with is
        cut first, and every mark still to come moves back)."""
        frame = max(1, self.channels * self.bitsPerSample // 8)
        count = int(self.samplesPerSec * max(0, int(ms)) / 1000) * frame
        if count <= 0 or self._closed:
            return
        silence = b'\x80' * count if self.bitsPerSample == 8 \
            else b'\x00' * count
        if not now:
            self.trim_tail()
            self.feed(silence)
            return
        with self._lock:
            if self.bitsPerSample == 16 and self._buffer and _trimming[0]:
                cut = min(_quiet_head(self._buffer, frame), int(
                    self.samplesPerSec * MAX_HEAD_MS / 1000) * frame)
                if cut and cut < len(self._buffer):
                    del self._buffer[:cut]
                    self._consumed += cut
            self._buffer[0:0] = silence
            self._consumed -= count
            if _silent() or self._stream is None:
                self._buffer.clear()
                self._consumed = self._fed

    def idle(self):
        """Block until everything fed has been played."""
        deadline = time.time() + 120
        with self._lock:
            while (self._buffer or self._marks) and not self._closed \
                    and self._stream is not None and time.time() < deadline:
                self._lock.wait(0.05)

    sync = idle

    def stop(self):
        with self._lock:
            self._buffer.clear()
            self._marks = []
            self._consumed = self._fed
            self._lock.notify_all()

    def pause(self, switch):
        with self._lock:
            self._paused = bool(switch)

    def close(self):
        self.stop()
        self._closed = True
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:                        # noqa: BLE001
                pass

    def setVolume(self, all=None, left=None, right=None):
        pass

    @property
    def busy(self):
        with self._lock:
            return bool(self._buffer)

    @classmethod
    def _idleCheck(cls):
        pass


def _safely(callback):
    _here.callback = True
    try:
        callback()
    except Exception:                                # noqa: BLE001
        pass
    finally:
        _here.callback = False


def _all_safely(callbacks):
    for callback in callbacks:
        _safely(callback)


def playWaveFile(fileName, asynchronous=True, isSpeechWaveFileCommand=False):
    """A wave file, through Titan's mixer."""
    try:
        from titan_access.engine import get_engine
        engine = get_engine()
        sound = getattr(engine, 'sound', None)
        if sound is not None and hasattr(sound, 'play_file'):
            sound.play_file(str(fileName))
            return
    except Exception:                                # noqa: BLE001
        pass
    try:
        from src.titan_core import sound as titan_sound
        titan_sound.play_sound_file(str(fileName))
    except Exception:                                # noqa: BLE001
        pass


def stopAll():
    with _LOCK:
        players = list(_players)
    for player in players:
        player.stop()


from . import permissive as _permissive  # noqa: E402
_permissive(globals())
