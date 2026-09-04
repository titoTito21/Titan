# -*- coding: utf-8 -*-
"""Titan, as the Elten platform sees it.

Copyright (C) 2026 titosoft. Part of the Elten API bridge, which is licensed
under the GNU General Public License version 3 or later; see `LICENSE` beside
this component.

Everything an application asks for ends here: a sentence to say, a sound to
play, a file to read, a string to translate. Two rules run through all of it.

**Everything is Titan's own.** The voice is whichever TTS the user chose, at
the rate they set, positioned where the application asked; a sound goes
through Titan's mixer with the user's theme volume and their stereo-or-HRTF
preference. An Elten application running here sounds like the rest of this
desktop because, for the person using it, it is this desktop.

**Nothing an application says is trusted.** An `.eltenapp` is a signed package
from Elten's repository, but a signature says who built something, not that it
is harmless, and the bridge must be safe with an application that is simply
wrong as well as one that is hostile. So every path is resolved inside a root
and re-checked after resolution, every handle is a number in a table this side
owns rather than anything the application can forge, every list is bounded,
and every string that reaches a widget is a string. An application cannot name
a file outside its own three directories, cannot reach another application's
data, and cannot ask Titan to run anything.
"""

import os
import threading
import time

#: How long a single sentence may be. An application that hands over a
#: megabyte of text is a bug; speaking it would lock the speech thread for
#: minutes and there is no way to interrupt from inside the utterance.
MAX_TEXT = 8000

#: How many entries a list dialog may carry, and how long a label may be.
MAX_ENTRIES = 2000
MAX_LABEL = 500

#: How many sounds one application may hold open at once. A leak in an
#: application must not become a leak in Titan's mixer.
MAX_SOUNDS = 64

#: How many voices the fire-and-forget pool plays at once.
POOL_VOICES = 8

_MISSING = object()


class PathRefused(Exception):
    """A path an application may not have, with the reason."""


class Paths(object):
    """The three roots an application has, and the only way out of them.

    `asset` is the unpacked package - read-only, and thrown away when the
    package changes. `data` is Elten's own `apps/data/<app>/`, deliberately
    SHARED with Elten so a saved game survives moving between the two.
    `cache` is losable.

    The confinement is the point of the class. `resolve` refuses anything
    that leaves its root - and it refuses it after `realpath`, not before,
    because `..` is only the obvious way out: a symbolic link, a Windows
    junction, or a name that normalises to something else all end up
    somewhere the application did not name. Checking the string it was given
    would pass every one of them.
    """

    KINDS = ('asset', 'data', 'cache')

    def __init__(self, asset='', data='', cache=''):
        self.roots = {'asset': asset, 'data': data, 'cache': cache}

    def root(self, kind):
        return self.roots.get(str(kind or ''), '')

    def resolve(self, kind, relative=''):
        """An absolute path inside one of the three roots.

        Raises `PathRefused` rather than answering something outside, because
        an application that asked for `../../elten.ini` should be told no and
        logged, not quietly handed a different file.
        """
        kind = str(kind or '')
        root = self.roots.get(kind, '')
        if not root:
            raise PathRefused('there is no %s directory for this application'
                              % (kind or 'such'))
        relative = str(relative or '')
        if relative.startswith(('/', '\\')) or (len(relative) > 1
                                                and relative[1] == ':'):
            raise PathRefused('an absolute path is not allowed here')
        # The root itself may not exist yet (`data` is made on first write),
        # so it is realpath-ed as far as it goes and the rest is normalised.
        base = os.path.realpath(root)
        full = os.path.realpath(os.path.join(base, relative))
        if full != base and not full.startswith(base + os.sep):
            raise PathRefused('that path is outside the application')
        return full

    def ensure(self, kind):
        root = self.roots.get(str(kind or ''), '')
        if root:
            try:
                os.makedirs(root, exist_ok=True)
            except OSError:
                pass
        return root


class Speaker(object):
    """An Elten application's voice, which is Titan's.

    An Elten application is self-voicing - everything it has to say, it says -
    so this is not an accessibility hint on top of a visible interface, it is
    the interface. It therefore goes exactly where the rest of Titan's speech
    goes, and the order is Titan's own, not a new answer invented here:

    1. **`stereo_speech.speak_stereo`** - the user's chosen TTS engine, at
       their rate, and POSITIONED. The position matters: Elten's own controls
       pan what they announce and a game says a thing where the thing is, so
       an application that asked for its voice on the left gets it on the
       left, the same way Cling's do.
    2. **The messenger** (`accessibility.messages.get_messenger()`) when that
       is not there - `accessible_output3`, which prefers a real screen
       reader over the platform's own TTS. So a user who reads this desktop
       with NVDA hears an Elten application through NVDA, and one who does
       not hears it through Titan's engine, with nothing to configure in
       either case.

    Kept behind an object so a test can replace it whole, and so importing
    `stereo_speech` - which reaches for SAPI over COM - happens the first
    time something speaks rather than when the bridge is loaded.
    """

    def __init__(self):
        self._stereo = _MISSING
        self._sound = _MISSING
        self.closed = False
        #: What was said, for the tests and the application's own log.
        self.spoken = []

    def _speech_module(self):
        if self._stereo is _MISSING:
            try:
                from src.titan_core import stereo_speech
                self._stereo = stereo_speech
            except Exception:
                self._stereo = None
        return self._stereo

    def _messenger(self):
        """Whatever Titan is configured to speak through - a real screen
        reader when one is running, the platform's TTS otherwise."""
        if self._sound is _MISSING:
            try:
                from src.accessibility.messages import get_messenger
                self._sound = get_messenger()
            except Exception:
                self._sound = None
        return self._sound

    def say(self, text, position=0.0, pitch=0.0, interrupt=True, wait=False):
        text = _text(text).strip()
        if not text or self.closed:
            return False
        self.spoken.append(text)
        module = self._speech_module()
        if module is not None:
            try:
                module.speak_stereo(text, position=_place(position)[0],
                                    pitch_offset=_clamp(pitch, -10.0, 10.0),
                                    async_mode=not wait)
                return True
            except Exception as error:
                print('[elten] speech failed: %s' % error)
        messenger = self._messenger()
        if messenger is not None:
            try:
                messenger.speaker.speak(text, interrupt=bool(interrupt))
                return True
            except Exception:
                pass
        return False

    def stop(self):
        module = self._speech_module()
        if module is not None:
            try:
                module.stop_stereo_speech()
                return True
            except Exception:
                pass
        messenger = self._messenger()
        if messenger is not None:
            try:
                messenger.speaker.silence()
                return True
            except Exception:
                pass
        return False

    def speaking(self):
        module = self._speech_module()
        asking = getattr(module, 'is_speaking', None) if module else None
        if asking is not None:
            try:
                return bool(asking())
            except Exception:
                pass
        return False

    def close(self):
        """Stop, and say nothing more. An application closed mid-sentence
        must not finish it after its window has gone."""
        self.closed = True
        self.stop()


class Sounds(object):
    """An application's audio: what it holds, and what it fires and forgets.

    Elten's own split. A held sound has a handle the application stops and
    starts; a pooled one is played and forgotten and the pool caps how many
    are audible at once. Both go through Titan's mixer, so the user's theme
    volume, their stereo or 3D preference and their output device all apply.

    **A handle is a number in this table**, never anything the application
    supplies. An application that invents one gets `false` back; it cannot
    reach a sound belonging to another application because there is one of
    these per running application and it holds only what it started.
    """

    def __init__(self, mixer=None):
        self.mixer = mixer if mixer is not None else Mixer()
        self._held = {}
        self._pool = []
        self._next = 0
        self._lock = threading.Lock()
        self.closed = False

    def create(self, path, spatial=False, position=0.0, loop=False):
        """A sound the application holds. `loop` belongs to the SOUND -
        an application sets it up once and then just calls `play`."""
        if self.closed or not path:
            return None
        with self._lock:
            if len(self._held) >= MAX_SOUNDS:
                return None
            self._next += 1
            handle = self._next
            self._held[handle] = {'path': path, 'live': None,
                                  'spatial': bool(spatial),
                                  'loop': bool(loop),
                                  'volume': 1.0,
                                  'paused': False,
                                  'position': position}
        return handle

    def play(self, handle, volume=None, position=None, loop=None):
        entry = self._entry(handle)
        if entry is None:
            return False
        if position is not None:
            entry['position'] = position
        if volume is not None:
            entry['volume'] = _clamp(volume, 0.0, 1.0)
        # A paused sound told to play carries on from where it stopped -
        # a game resuming a flight it held for a shot must not hear the
        # clip start again.
        if entry['live'] is not None and entry.get('paused'):
            entry['paused'] = False
            if self.mixer.pause(entry['live'], False):
                return True
        self.stop(handle)
        repeating = entry.get('loop') if loop is None else bool(loop)
        pan, elevation, falloff = _place(entry['position'])
        live = self.mixer.start(entry['path'], pan,
                                gain=_clamp(entry['volume'] * falloff,
                                            0.0, 1.0),
                                loop=bool(repeating), elevation=elevation)
        entry['live'] = live
        entry['paused'] = False
        return live is not None

    def pause(self, handle, paused=True):
        entry = self._entry(handle)
        if entry is None or entry['live'] is None:
            return False
        entry['paused'] = bool(paused)
        return self.mixer.pause(entry['live'], bool(paused))

    def stop(self, handle):
        entry = self._entry(handle)
        if entry is None:
            return False
        live, entry['live'] = entry['live'], None
        if live is not None:
            self.mixer.stop(live)
        return True

    def playing(self, handle):
        entry = self._entry(handle)
        return bool(entry and entry['live'] is not None
                    and self.mixer.busy(entry['live']))

    def set_volume(self, handle, volume):
        entry = self._entry(handle)
        if entry is None:
            return False
        entry['volume'] = _clamp(volume, 0.0, 1.0)
        return self._apply(entry)

    def set_position(self, handle, position):
        """Where it is now. The application's OWN volume is kept: moving a
        sound used to re-gain it at 1.0, so a game that placed a quiet
        sound and then moved it heard it jump to full."""
        entry = self._entry(handle)
        if entry is None:
            return False
        entry['position'] = position
        return self._apply(entry)

    def _apply(self, entry):
        if entry['live'] is None:
            return True
        pan, elevation, falloff = _place(entry['position'])
        return self.mixer.set_gain(entry['live'], pan,
                                   _clamp(entry['volume'] * falloff, 0.0, 1.0),
                                   elevation)

    def close_sound(self, handle):
        self.stop(handle)
        with self._lock:
            self._held.pop(_handle(handle), None)
        return True

    def pool_play(self, path, volume=1.0, max_voices=POOL_VOICES,
                  position=0.0, loop=False):
        """Fire and forget, with a ceiling on how many are audible.

        The ceiling is not decoration: a game that plays a click per keypress
        will, on a held arrow key, ask for thirty a second, and a mixer given
        all of them runs out of channels and goes silent - which reads as the
        game breaking rather than as too many sounds.
        """
        if self.closed or not path:
            return None
        try:
            ceiling = max(1, min(int(max_voices), POOL_VOICES))
        except (TypeError, ValueError):
            ceiling = POOL_VOICES
        with self._lock:
            self._pool = [live for live in self._pool if self.mixer.busy(live)]
            while len(self._pool) >= ceiling:
                self.mixer.stop(self._pool.pop(0))
        pan, elevation, falloff = _place(position)
        live = self.mixer.start(path, pan,
                                gain=_clamp(_clamp(volume, 0.0, 1.0) * falloff,
                                            0.0, 1.0),
                                loop=bool(loop), elevation=elevation)
        if live is None:
            return None
        with self._lock:
            self._pool.append(live)
        return True

    def close_pool(self):
        with self._lock:
            pool, self._pool = self._pool, []
        for live in pool:
            self.mixer.stop(live)
        return True

    def close(self):
        self.closed = True
        self.close_pool()
        with self._lock:
            held, self._held = list(self._held.values()), {}
        for entry in held:
            if entry['live'] is not None:
                self.mixer.stop(entry['live'])
        self.mixer.close()

    def _entry(self, handle):
        return self._held.get(_handle(handle))


class Stream(object):
    """A URL, played as audio through Titan's own mixer.

    Elten's `Player` control is a radio station or a podcast episode, and
    Elten plays it with the BASS stack it ships. Titan's mixer is pygame,
    which plays FILES - so what is missing between a URL and this desktop's
    sound is the decoding, and that is what PyAV does here: the container is
    opened (an Icecast stream, an mp3, an m4a), decoded, resampled to
    whatever format the live mixer is in, and handed to Titan's mixer a
    second at a time on a channel of its own.

    Doing it that way rather than opening an output device of its own is
    the point. The user's theme volume applies, their output device
    applies, it stops when Titan's sound stops, and a radio station is not
    the one thing on this desktop that is louder than everything else.

    A live stream has no length and cannot be sought; a finished file has
    both. `duration` answering None is what an application reads to tell
    the two apart, and it is answered honestly rather than guessed.
    """

    #: How much audio is handed over at a time. Long enough that a busy
    #: moment on the GUI thread cannot starve it, short enough that a
    #: pause or a stop is heard at once.
    CHUNK_SECONDS = 1.0

    #: How much is decoded ahead. A radio stream arrives at real time, so
    #: this is what absorbs a hiccup in the network.
    BUFFER_CHUNKS = 8

    def __init__(self, mixer, url, label=''):
        self.mixer = mixer
        self.url = str(url or '')
        self.label = str(label or '')
        self.error = None
        self.duration = None
        self.opened = False
        self.finished = False
        self._paused = False
        self._closed = False
        self._played = 0.0
        self.volume = 1.0
        self._seek_to = None
        self._channel = None
        self._chunks = []
        self._lock = threading.Lock()
        self._worker = None
        self._pump = None
        self._start()

    # ------------------------------------------------------------ opening
    def _start(self):
        try:
            import av                                        # noqa: F401
        except Exception as error:
            self.error = 'no decoder: %s' % error
            return
        self._worker = threading.Thread(target=self._decode, daemon=True)
        self._worker.start()
        # Wait a moment for the container to open, so an application can ask
        # `opened?` straight afterwards and get a true answer - which is
        # what decides whether it shows a player at all.
        deadline = time.time() + 12.0
        while time.time() < deadline and not self.opened and self.error is None:
            time.sleep(0.05)

    def _format(self):
        """The format the LIVE mixer is in - never a guess. Handing pygame
        a buffer at the wrong rate plays it at the wrong speed."""
        try:
            import pygame
            found = pygame.mixer.get_init()
        except Exception:
            found = None
        if not found:
            return 44100, 2
        rate, _size, channels = found
        return int(rate), max(1, min(2, abs(int(channels))))

    def _decode(self):
        try:
            import av
            import numpy
        except Exception as error:
            self.error = 'no decoder: %s' % error
            return
        rate, channels = self._format()
        try:
            options = {'user_agent': 'Titan-EltenBridge/1.0',
                       'rw_timeout': '15000000'}
            container = av.open(self.url, options=options, timeout=15.0)
        except Exception as error:
            self.error = '%s' % error
            return
        try:
            track = next((s for s in container.streams if s.type == 'audio'),
                         None)
            if track is None:
                self.error = 'there is no audio in it'
                return
            if container.duration:
                self.duration = float(container.duration) / 1000000.0
            layout = 'stereo' if channels == 2 else 'mono'
            resampler = av.AudioResampler(format='s16', layout=layout,
                                          rate=rate)
            self.opened = True
            spare = numpy.zeros((0, channels), dtype=numpy.int16)
            want = int(rate * self.CHUNK_SECONDS)
            while not self._closed:
                target, self._seek_to = self._seek_to, None
                if target is not None:
                    try:
                        container.seek(int(target * 1000000),
                                       stream=track, any_frame=False)
                        with self._lock:
                            self._chunks = []
                        self._played = float(target)
                        spare = numpy.zeros((0, channels), dtype=numpy.int16)
                    except Exception:
                        pass
                while len(self._chunks) >= self.BUFFER_CHUNKS \
                        and not self._closed and self._seek_to is None:
                    time.sleep(0.05)
                if self._closed or self._seek_to is not None:
                    continue
                try:
                    packet = next(container.demux(track))
                except (StopIteration, Exception):
                    break
                for frame in self._frames(packet):
                    for piece in resampler.resample(frame):
                        block = piece.to_ndarray().reshape(-1, channels)
                        spare = numpy.concatenate((spare, block))
                        while len(spare) >= want:
                            self._offer(spare[:want])
                            spare = spare[want:]
            if len(spare) and not self._closed:
                self._offer(spare)
        except Exception as error:
            if self.error is None and not self._closed:
                self.error = '%s' % error
        finally:
            self.finished = True
            try:
                container.close()
            except Exception:
                pass

    def _frames(self, packet):
        try:
            return list(packet.decode())
        except Exception:
            return []

    def _offer(self, block):
        try:
            import pygame
            clip = pygame.mixer.Sound(buffer=block.tobytes())
        except Exception:
            return
        with self._lock:
            self._chunks.append(clip)
        if self._pump is None:
            self._pump = threading.Thread(target=self._feed, daemon=True)
            self._pump.start()

    # ------------------------------------------------------------ playing
    def _feed(self):
        """Hand Titan's mixer the next second whenever it has room.

        `Channel.queue` holds exactly one, so a channel with something
        playing and something queued is full and the loop simply waits -
        which is also what keeps a live stream from running ahead of the
        clock.
        """
        while not self._closed:
            if self._paused:
                time.sleep(0.05)
                continue
            channel = self._reserve()
            if channel is None:
                time.sleep(0.1)
                continue
            try:
                if channel.get_queue() is not None:
                    time.sleep(0.05)
                    continue
                with self._lock:
                    clip = self._chunks.pop(0) if self._chunks else None
                if clip is None:
                    if self.finished and not channel.get_busy():
                        break
                    time.sleep(0.05)
                    continue
                clip.set_volume(self.volume * self.mixer._theme_volume())
                if channel.get_busy():
                    channel.queue(clip)
                else:
                    channel.play(clip)
                self._played += self.CHUNK_SECONDS
            except Exception:
                time.sleep(0.1)

    def _reserve(self):
        if self._channel is not None:
            return self._channel
        try:
            import pygame
            if not pygame.mixer.get_init():
                return None
            self._channel = pygame.mixer.find_channel(True)
        except Exception:
            self._channel = None
        return self._channel

    # -------------------------------------------------------- the controls
    def play(self):
        self._paused = False
        try:
            if self._channel is not None:
                self._channel.unpause()
        except Exception:
            pass
        return True

    def pause(self):
        self._paused = True
        try:
            if self._channel is not None:
                self._channel.pause()
        except Exception:
            pass
        return True

    def paused(self):
        return self._paused

    def playing(self):
        if self._closed or self._paused:
            return False
        try:
            return bool(self._channel is not None and self._channel.get_busy())
        except Exception:
            return False

    def position(self):
        return round(self._played, 2)

    def set_volume(self, level):
        """How loud, on top of the user's theme volume - never instead of
        it. A radio station is not the one thing on this desktop that
        ignores what the user set."""
        self.volume = _clamp(level, 0.0, 1.0)
        return self.volume

    def seek(self, seconds):
        """Only where there is something to seek THROUGH. A live radio
        stream has no length and no past, and answering True to a seek that
        cannot happen is how an application ends up showing a position that
        is not where the sound is."""
        if self.duration is None:
            return False
        self._seek_to = max(0.0, float(seconds))
        return True

    def close(self):
        self._closed = True
        try:
            if self._channel is not None:
                self._channel.stop()
        except Exception:
            pass
        with self._lock:
            self._chunks = []
        self._channel = None
        return True

    def status(self):
        return {'opened': bool(self.opened), 'error': self.error,
                'volume': self.volume,
                'duration': self.duration, 'position': self.position(),
                'playing': self.playing(), 'paused': self._paused,
                'finished': bool(self.finished and not self.playing())}


class Mixer(object):
    """Titan's sound, as this bridge needs it.

    Deliberately the same shape as Cling's: `start` answers a handle or None,
    and everything else takes one. What it is underneath is whatever the user
    has - OpenAL when they turned 3D on, an ordinary panned channel otherwise
    - and either way the theme volume applies, because an Elten application
    is not louder than the desktop it is running on.
    """

    def __init__(self):
        self._sound = _MISSING
        self._spatial = _MISSING
        self._pygame = _MISSING
        self.closed = False
        self.played = []

    def _sound_module(self):
        if self._sound is _MISSING:
            try:
                from src.titan_core import sound
                self._sound = sound
            except Exception:
                self._sound = None
        return self._sound

    def _spatial_module(self):
        if self._spatial is _MISSING:
            try:
                from src.titan_core import spatial_audio
                self._spatial = spatial_audio
            except Exception:
                self._spatial = None
        return self._spatial

    def _pygame_mixer(self):
        if self._pygame is _MISSING:
            try:
                import pygame
                module = self._sound_module()
                if module is not None and not pygame.mixer.get_init():
                    module.initialize_sound()
                self._pygame = pygame if pygame.mixer.get_init() else None
            except Exception:
                self._pygame = None
        return self._pygame

    def _mode(self):
        module = self._sound_module()
        if module is None:
            return 'none'
        try:
            return module.get_sound_mode()
        except Exception:
            return 'stereo'

    def _theme_volume(self):
        module = self._sound_module()
        if module is None:
            return 1.0
        try:
            settings = module.load_settings()
            return _clamp(int(settings.get('sound', {}).get(
                'sound_theme_volume', 100)) / 100.0, 0.0, 1.0)
        except Exception:
            return 1.0

    def start(self, path, pan=0.0, gain=1.0, loop=False, elevation=0.0):
        if self.closed or not path or not os.path.isfile(path):
            return None
        self.played.append((os.path.basename(path), round(float(pan), 3),
                            round(float(gain), 3)))
        gain = _clamp(gain, 0.0, 1.0)
        if self._mode() == '3d':
            source = self._spatial_start(path, pan, gain, loop, elevation)
            if source is not None:
                return source
        return self._channel_start(path, pan, gain, loop)

    def _spatial_start(self, path, pan, gain, loop, elevation=0.0):
        spatial = self._spatial_module()
        if spatial is None:
            return None
        try:
            if not spatial.spatial_available():
                return None
            azimuth = spatial.pan_to_azimuth((float(pan) + 1.0) / 2.0)
            height = _clamp(elevation, -90.0, 90.0)
            volume = gain * self._theme_volume()
            try:
                source = spatial.play_file(path, azimuth, height, volume,
                                           loop=bool(loop))
            except TypeError:
                source = spatial.play_file(path, azimuth, height, volume)
            return _Spatial(source) if source is not None else None
        except Exception as error:
            print('[elten] 3D playback failed: %s' % error)
            return None

    def _channel_start(self, path, pan, gain, loop):
        pygame = self._pygame_mixer()
        if pygame is None:
            return None
        try:
            clip = pygame.mixer.Sound(path)
            channel = pygame.mixer.find_channel()
            if channel is None:
                return None
            self._set_volume(channel, pan, gain * self._theme_volume())
            channel.play(clip, loops=-1 if loop else 0)
            return channel
        except Exception:
            return None

    def _set_volume(self, channel, pan, volume):
        """Constant power, as everywhere else in Titan: a sound that crosses
        the listener must not dip as it passes the middle."""
        import math
        volume = _clamp(volume, 0.0, 1.0)
        try:
            position = _clamp((float(pan) + 1.0) / 2.0, 0.0, 1.0)
            angle = position * (math.pi / 2.0)
            channel.set_volume(_clamp(math.cos(angle) * volume, 0.0, 1.0),
                               _clamp(math.sin(angle) * volume, 0.0, 1.0))
        except Exception:
            try:
                channel.set_volume(volume)
            except Exception:
                pass

    def set_gain(self, handle, pan=0.0, gain=1.0, elevation=0.0):
        """Move a sound that is already playing, and re-gain it.

        Both halves matter and both used to be missing on the path a user
        with 3D on is actually on: a clay target is thrown and then told
        where it has got to on every frame, so a `set_gain` that refused a
        spatial handle left the disc hanging in the middle of the room at
        one volume for its whole flight - playing, correct, and not the
        game.
        """
        if handle is None:
            return False
        if isinstance(handle, _Spatial):
            spatial = self._spatial_module()
            if spatial is None:
                return False
            moved = False
            try:
                moved = bool(spatial.move_source(
                    handle.source, spatial.pan_to_azimuth(
                        (float(pan) + 1.0) / 2.0),
                    _clamp(elevation, -90.0, 90.0)))
            except Exception:
                moved = False
            setter = getattr(spatial, 'set_gain', None)
            if setter is None:
                return moved
            try:
                return bool(setter(handle.source,
                                   _clamp(gain, 0.0, 1.0) * self._theme_volume())) \
                    or moved
            except Exception:
                return moved
        try:
            self._set_volume(handle, pan, gain * self._theme_volume())
            return True
        except Exception:
            return False

    def pause(self, handle, paused=True):
        """Hold a sound where it is. A game pauses the flight while it
        works out whether the shot hit, and resuming has to carry on from
        where it stopped rather than start the clip again."""
        if handle is None:
            return False
        if isinstance(handle, _Spatial):
            spatial = self._spatial_module()
            pauser = getattr(spatial, 'pause_source', None)
            if pauser is None:
                return False
            try:
                return bool(pauser(handle.source, bool(paused)))
            except Exception:
                return False
        try:
            handle.pause() if paused else handle.unpause()
            return True
        except Exception:
            return False

    def busy(self, handle):
        if handle is None:
            return False
        if isinstance(handle, _Spatial):
            spatial = self._spatial_module()
            if spatial is None:
                return False
            try:
                return bool(spatial.is_playing(handle.source))
            except Exception:
                return False
        try:
            return bool(handle.get_busy())
        except Exception:
            return False

    def stop(self, handle):
        if handle is None:
            return
        if isinstance(handle, _Spatial):
            spatial = self._spatial_module()
            if spatial is not None:
                try:
                    spatial.stop_source(handle.source)
                except Exception:
                    pass
            return
        try:
            handle.stop()
        except Exception:
            pass

    def cue(self, name, pan=0.0):
        """One of Titan's own interface sounds, by the name the theme uses."""
        module = self._sound_module()
        if module is None or self.closed:
            return False
        try:
            return bool(module.play_sound(name))
        except Exception:
            return False

    def close(self):
        self.closed = True


def _place(position):
    """Elten's own coordinates, as Titan's mixer takes them.

    A place in Elten is `[x, y, z]` in metres with the listener at the
    origin - x to the right, y up, z in front - and that is what crosses
    the wire, unconverted. The conversion belongs HERE, because this is
    the only side that knows what Titan's mixer is: a pan of -1 to 1, an
    elevation in degrees, and a gain.

    So it is an angle, not a division. A sound a metre to the side with
    nothing in front of it is hard over - which is what a game that pans
    by x expects - and the same metre to the side ten metres away is
    nearly straight ahead, which a division by a fixed number gets wrong
    in both directions. Skeet's clay target is `[-1..1, 1, 0]`: it
    crosses the whole stereo image, rises overhead as it passes, and is
    loudest there, because that is where it really is.

    Answers `(pan, elevation, gain)`. A bare number is already a pan and
    is left alone - most applications place a sound that simply way.
    """
    import math
    if position is None:
        return 0.0, 0.0, 1.0
    if isinstance(position, (int, float)):
        return _clamp(position, -1.0, 1.0), 0.0, 1.0
    if isinstance(position, dict):
        position = [position.get('x', position.get(u'x', 0.0)),
                    position.get('y', position.get(u'y', 0.0)),
                    position.get('z', position.get(u'z', 0.0))]
    if not isinstance(position, (list, tuple)):
        return 0.0, 0.0, 1.0
    values = list(position) + [0.0, 0.0, 0.0]
    x = _clamp(values[0], -1e4, 1e4)
    y = _clamp(values[1], -1e4, 1e4)
    z = _clamp(values[2], -1e4, 1e4)
    flat = math.hypot(x, z)
    pan = 0.0 if flat <= 1e-6 else _clamp(x / flat, -1.0, 1.0)
    elevation = 0.0 if (flat <= 1e-6 and abs(y) <= 1e-6) else \
        _clamp(math.degrees(math.atan2(y, flat)), -90.0, 90.0)
    # Within arm's reach nothing is quieter; past that it falls away the
    # way a real one does. A game that never leaves a metre - which is
    # most of them - is unaffected by this entirely.
    distance = math.sqrt(x * x + y * y + z * z)
    gain = 1.0 if distance <= 1.0 else _clamp(1.0 / distance, 0.05, 1.0)
    return pan, elevation, gain


class _Spatial(object):
    """An OpenAL source, told apart from a channel by its type."""

    __slots__ = ('source',)

    def __init__(self, source):
        self.source = source


# ------------------------------------------------------------------ helpers
def _text(value, limit=MAX_TEXT):
    """Whatever the application sent, as a string a widget can hold."""
    if value is None:
        return ''
    if not isinstance(value, str):
        value = str(value)
    if len(value) > limit:
        value = value[:limit]
    # A control character in a label is at best invisible and at worst
    # confuses the control it is put into; a newline is kept because a
    # multi-line message is a real thing.
    return ''.join(character for character in value
                   if character in '\r\n\t' or character >= ' ')


def _label(value):
    return _text(value, MAX_LABEL)


def _clamp(value, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return low
    if value != value:                                             # NaN
        return low
    return max(low, min(high, value))


def _handle(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1
