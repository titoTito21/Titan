# -*- coding: utf-8 -*-
"""The Cling host: everything a Cling application can do, expressed in Titan.

This is the emulator half of the subsystem.  A Klango application talks to a
platform that speaks, plays a sound at a place, asks a question and remembers a
score; Cling gives it those same four things, implemented over Titan's own
speech, mixer and settings, so the application does not know - and must not
need to know - which platform it is running on.

Three decisions are worth stating, because everything else follows from them.

**The voice is Titan's.**  Klango shipped its own synthesiser and every
application inherited it; a Cling application inherits the voice the user
already chose, at the rate they already set, through `stereo_speech` - which
also means an application can speak from a PLACE (a mole at the left of the
board says so in the left ear), which is what `speak_stereo`'s position and
pitch arguments have always been for.

**A sound at a place goes through whichever of Titan's two backends the user
turned on.**  With 3D on it is `spatial_audio` and a real HRTF azimuth; with
stereo it is a pan; with sound off it is nothing at all, and the application
still runs, because a board that can only be heard would be unplayable for the
one user who has their headphones out.

**Nothing here touches wx.**  The host is driven by an engine, the engine by a
surface, and only the surface is a window - so an engine can be run in a test,
at a speed a test chooses, with no display, no mixer and no voice.
"""

import math
import os
import time

_MISSING = object()


def _call(function, *values, **named):
    """Call it, and again without the extras if this Titan has not got them.

    Cling asks `spatial_audio` to loop a source, which older copies of that
    module cannot do. A Klango application should lose the looping rather
    than the sound.
    """
    try:
        return function(*values, **named)
    except TypeError:
        return function(*values)


class Speaker(object):
    """Titan's speech, or the nearest thing available.

    Kept behind an object so a test can replace it whole, and so the import of
    `stereo_speech` - which reaches for SAPI over COM - happens the first time
    something speaks rather than when Cling is loaded.
    """

    def __init__(self):
        self._stereo = _MISSING
        self._sound = _MISSING
        self.closed = False
        self.spoken = []          # what was said, for the tests and the log

    def _speech_module(self):
        if self._stereo is _MISSING:
            try:
                from src.titan_core import stereo_speech
                self._stereo = stereo_speech
            except Exception:
                self._stereo = None
        return self._stereo

    def _sound_module(self):
        if self._sound is _MISSING:
            try:
                from src.titan_core import sound
                self._sound = sound
            except Exception:
                self._sound = None
        return self._sound

    def say(self, text, position=0.0, pitch=0.0, interrupt=True, wait=False):
        text = (text or '').strip()
        if not text or self.closed:
            return False
        self.spoken.append(text)
        module = self._speech_module()
        if module is not None:
            try:
                module.speak_stereo(text, position=float(position),
                                    pitch_offset=float(pitch),
                                    async_mode=not wait)
                return True
            except Exception as error:
                print('[cling] speech failed: %s' % error)
        module = self._sound_module()
        if module is not None:
            try:
                module.speak(text, interrupt=interrupt)
                return True
            except Exception:
                pass
        return False

    def close(self):
        """Stop, and say nothing more. An application closed mid-sentence
        must not finish it after its window has gone."""
        self.closed = True
        self.stop()

    def stop(self):
        module = self._speech_module()
        if module is not None:
            try:
                module.stop_stereo_speech()
                return
            except Exception:
                pass
        module = self._sound_module()
        if module is not None:
            try:
                module.stop_speech()
            except Exception:
                pass


class Mixer(object):
    """Sound at a place, and sound that keeps going.

    `sound.play_sound_file` is what Titan uses everywhere and it is what a
    one-shot goes through, so a Cling application obeys the user's sound theme
    volume, their 3D-or-stereo choice and their haptics exactly like the rest
    of the desktop.  Two things that module has never needed and a game cannot
    do without are done here instead: a sound that LOOPS (a board's ambience
    runs for the length of a level) and a sound with a GAIN of its own (the far
    row of a board is quieter than the near one, which is most of what makes a
    board have depth).
    """

    #: How many decoded clips to keep. An application has a few dozen sounds
    #: and a few pitches; the ceiling is only there so a run that generates
    #: names cannot fill memory.
    CLIP_CACHE = 256

    #: How many handles to keep before tidying the finished ones out. A board
    #: plays a few sounds a second and they are all short.
    LIVE_BEFORE_TIDYING = 64

    def __init__(self):
        self._sound = _MISSING
        self._spatial = _MISSING
        self._pygame = _MISSING
        #: True once the application has been closed. See `close`.
        self.closed = False
        self._loops = []
        #: Everything that is playing, not only what loops. Closing an
        #: application has to silence it, and a one-shot that outlives the
        #: window - a long announcement, a level's own fanfare - is a sound
        #: still coming out of a game that is not there any more.
        self._live = []
        #: (file, pitch) -> the `pygame.mixer.Sound` for it. A board asks for
        #: the same handful of sounds all game; decoding one is not free and a
        #: pitched one is a resample.
        self._clips = {}
        self.played = []          # (name, pan, gain), for the tests

    # ------------------------------------------------------------- modules
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
            return max(0.0, min(1.0, int(settings.get('sound', {}).get(
                'sound_theme_volume', 100)) / 100.0))
        except Exception:
            return 1.0

    # ------------------------------------------------------------ playback
    def start(self, path, pan=0.0, elevation=0.0, gain=1.0, cents=0.0,
              loop=False, repeats=0):
        """Start a sound and hand back what is playing it, or None.

        **The place is not optional.** Titan's `sound_mode` decides whether
        Titan's OWN interface sounds are panned, and it is off by default; a
        Klango board, though, is not drawn - it is heard, and a player aims by
        where a mole sounds. Panning it only when a global preference happens
        to be on would not make Cling quieter, it would make it unplayable. So
        Cling places its own sounds itself, always, and `sound_mode` decides
        only whether it can use the better of the two ways: HRTF when the user
        has turned 3D on, an ordinary stereo pan otherwise.

        **A handle, not a boolean**, because Klango asks. Its sequences step
        on when what they are playing has finished (`_Snd_IsPlaying`), so a
        one-shot that answers "nothing is playing" the instant it starts makes
        every spoken menu item and every announcement collapse into the next.

        `cents` is Klango's own `freq`: a pitch shift, in hundredths of a
        semitone, which is how its boards tell one ROW from another - the far
        row of Mole No More is a semitone lower than the near one, and without
        it a board is a line rather than a grid.
        """
        if not path or not os.path.isfile(path):
            return None
        self.played.append((os.path.basename(path), round(float(pan), 3),
                            round(float(gain), 3)))
        gain = max(0.0, min(1.0, float(gain)))

        if self.closed:
            # The window has gone. Nothing this application asked for before
            # it noticed may still arrive: an emulated application runs on a
            # thread of its own and can be a frame or two behind.
            return None

        if self._mode() == '3d':
            source = self._play_spatial(path, pan, elevation, gain, cents, loop)
            if source is not None:
                return self._remember(source)

        # Titan's own `play_sound_file` drops the pan when `sound_mode` is
        # 'none' and has no gain at all, so a placed sound is put on a channel
        # here - the same pan law and the same theme volume, applied whatever
        # the user's preference for Titan's interface sounds.
        channel = self._play_placed(path, pan, gain, cents, loop, repeats)
        if channel is not None:
            return self._remember(channel)

        module = self._sound_module()
        if module is None:
            return None
        try:
            started = module.play_sound_file(path, (float(pan) + 1.0) / 2.0,
                                             float(elevation))
            return _Anonymous() if started else None
        except Exception as error:
            print('[cling] playback failed: %s' % error)
            return None

    def play(self, path, pan=0.0, elevation=0.0, gain=1.0, cents=0.0):
        """One sound, at a place. `pan` is -1 (left) .. 1 (right)."""
        return self.start(path, pan, elevation, gain, cents) is not None

    def loop(self, path, pan=0.0, gain=0.6, elevation=0.0, cents=0.0):
        """Start a sound that keeps playing. Returns a handle for `stop`."""
        handle = self.start(path, pan, elevation, gain, cents, loop=True)
        if handle is not None:
            self._loops.append(handle)
        return handle

    def _remember(self, handle):
        """Hold on to what is playing, so `stop_all` can really stop it."""
        self._live.append(handle)
        if len(self._live) > self.LIVE_BEFORE_TIDYING:
            self._live = [held for held in self._live if self.busy(held)]
        return handle

    def length(self, path):
        """How long a sound is, in seconds.

        Klango's sequences are built out of this - `_Snd_GetProperty(name,
        "sampleTime")` is what decides when the next element starts - so
        answering 0 puts a whole sequence at one moment.
        """
        if not path or not os.path.isfile(path):
            return 0.0
        pygame = self._pygame_mixer()
        if pygame is None:
            return 0.0
        try:
            return float(self._clip(pygame, path).get_length())
        except Exception:
            return 0.0

    def set_gain(self, handle, pan=0.0, gain=1.0, elevation=0.0):
        """Where a sound is and how loud it is, while it plays.

        This is `_Snd_Action`'s `vol` / `volMul` and the step of a
        `pos3dSlide`, and it is the one call the WHOLE of Klango's sound
        layer is built on top of: an ambience is started at nothing and faded
        in (`volMulSlide = {0, 1, speed}`), every dialog ducks the game to a
        fifth while it is up, and a clay pigeon that crosses the listener is
        re-placed and re-gained at every frame of its flight.

        It used to refuse a 3D handle outright - and 3D is the path a Cling
        user is on, because a Klango board is aimed at by ear and this
        subsystem asks for HRTF whenever the user has it. So on the path that
        matters nothing ever came up from the zero it was started at: Dice
        Poker's, Long Jump's and Skeet's backgrounds were started, looped and
        never heard, and Skeet's disc was thrown and stayed where it was
        thrown from. OpenAL can do both - a source renders from wherever it
        is at that instant, and `AL_GAIN` is live - so both are done here.
        `set_gain` on `spatial_audio` is asked for by name, because a Cling
        packaged beside an older Titan should lose the fade rather than the
        sound.
        """
        if handle is None or isinstance(handle, _Anonymous):
            return False
        if isinstance(handle, _Spatial):
            spatial = self._spatial_module()
            if spatial is None:
                return False
            volume = max(0.0, min(1.0, float(gain))) * self._theme_volume()
            moved = False
            try:
                moved = bool(spatial.move_source(
                    handle.source,
                    spatial.pan_to_azimuth((float(pan) + 1.0) / 2.0),
                    float(elevation)))
            except Exception:
                moved = False
            setter = getattr(spatial, 'set_gain', None)
            if setter is None:
                return moved
            try:
                return bool(setter(handle.source, volume)) or moved
            except Exception:
                return moved
        try:
            self._set_volume(handle, pan, gain * self._theme_volume())
            return True
        except Exception:
            return False

    def set_velocity(self, handle, velocity):
        """How fast a sound is moving - `_Snd_Action`'s `vel3d`.

        Only the 3D path can do anything with it: OpenAL computes the Doppler
        shift continuously, which is not something a stereo channel can be
        told to do to a clip it is already playing.
        """
        if handle is None or not isinstance(handle, _Spatial):
            return False
        spatial = self._spatial_module()
        setter = getattr(spatial, 'set_velocity', None) if spatial else None
        if setter is None:
            return False
        try:
            return bool(setter(handle.source, *velocity))
        except Exception:
            return False

    def pause(self, handle, paused=True):
        """Hold a sound where it is - `_Snd_Action`'s `pause` / `resume`.

        Klango pauses a whole GROUP when a dialog opens: the game's own sounds
        stop where they are and carry on when it closes, which is why a splash
        over a running game is quiet rather than a splash with the game still
        going on underneath it.
        """
        if handle is None:
            return False
        if isinstance(handle, _Spatial):
            spatial = self._spatial_module()
            stop = getattr(spatial, 'pause_source', None) if spatial else None
            if stop is None:
                return False
            try:
                stop(handle.source, paused)
                return True
            except Exception:
                return False
        if isinstance(handle, _Anonymous):
            return False
        try:
            handle.pause() if paused else handle.unpause()
            return True
        except Exception:
            return False

    def busy(self, handle):
        """Is this still playing? Klango's sequences turn on the answer."""
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
        if isinstance(handle, _Anonymous):
            return False
        try:
            return bool(handle.get_busy())
        except Exception:
            return False

    # -------------------------------------------------------------- pieces
    def _play_spatial(self, path, pan, elevation, gain, cents, loop):
        spatial = self._spatial_module()
        if spatial is None:
            return None
        try:
            if not spatial.spatial_available():
                return None
            azimuth = spatial.pan_to_azimuth((float(pan) + 1.0) / 2.0)
            volume = gain * self._theme_volume()
            if cents:
                # A pitch shift on OpenAL is a sample rate: the same samples,
                # told they were recorded at a different speed.
                decoded = spatial._decode_to_mono_pcm(path)
                if decoded:
                    pcm, rate = decoded[0], decoded[1]
                    source = _call(spatial.play_pcm,
                                   pcm, int(rate * _pitch_ratio(cents)), 1, 2,
                                   azimuth, float(elevation), volume,
                                   loop=bool(loop))
                    return _Spatial(source) if source is not None else None
            source = _call(spatial.play_file, path, azimuth, float(elevation),
                           volume, loop=bool(loop))
            return _Spatial(source) if source is not None else None
        except Exception as error:
            print('[cling] 3D playback failed: %s' % error)
            return None

    def _play_placed(self, path, pan, gain, cents=0.0, loop=False, repeats=0):
        pygame = self._pygame_mixer()
        if pygame is None:
            return None
        try:
            clip = self._clip(pygame, path, cents)
            if clip is None:
                return None
            channel = pygame.mixer.find_channel()
            if channel is None:
                return None
            self._set_volume(channel, pan, gain * self._theme_volume())
            channel.play(clip, loops=-1 if loop else max(0, int(repeats)))
            return channel
        except Exception:
            return None

    def _clip(self, pygame, path, cents=0.0):
        """The sound, at the pitch it was asked for. Both are cached.

        A pitch shift is a resample: the same samples read at a different
        speed, which is what Klango's own `freq` does to a sample. It is done
        once per (file, pitch) because a board asks for the same handful of
        sounds at the same handful of pitches for the whole of a game.
        """
        key = (path, round(float(cents or 0.0), 1))
        clip = self._clips.get(key)
        if clip is not None:
            return clip
        clip = pygame.mixer.Sound(path)
        if key[1]:
            clip = _pitched(pygame, clip, key[1]) or clip
        if len(self._clips) < self.CLIP_CACHE:
            self._clips[key] = clip
        return clip

    def _set_volume(self, channel, pan, volume):
        """Put the channel where the sound is. Always - see `start`.

        The law is CONSTANT POWER (`cos`/`sin` of a quarter turn), not the
        linear one, because in Cling a sound moves: Skeet's clay pigeon
        crosses the listener while it plays, and a linear pan makes it 3 dB
        quieter exactly as it passes the middle - which is the moment it is
        closest and the distance model is making it loudest. The two fight,
        and what is heard is a disc that dips as it goes by. Equal power is
        also what a menu spread from -60 to +60 degrees needs: every item the
        same loudness, wherever it is.
        """
        volume = max(0.0, min(1.0, volume))
        try:
            position = max(0.0, min(1.0, (float(pan) + 1.0) / 2.0))
            angle = position * (math.pi / 2.0)
            channel.set_volume(max(0.0, min(1.0, math.cos(angle) * volume)),
                               max(0.0, min(1.0, math.sin(angle) * volume)))
        except Exception:
            try:
                channel.set_volume(volume)
            except Exception:
                pass

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
        else:
            try:
                handle.stop()
            except Exception:
                pass
        if handle in self._loops:
            self._loops.remove(handle)

    def stop_all(self):
        """Silence. Everything this mixer started, not only what loops."""
        for handle in list(self._live) + list(self._loops):
            self.stop(handle)
        self._live = []
        self._loops = []
        spatial = self._spatial_module()
        if spatial is not None:
            try:
                spatial.stop_all()
            except Exception:
                pass

    def close(self):
        """Stop everything and refuse to start anything else."""
        self.closed = True
        self.stop_all()


class _Spatial(object):
    """An OpenAL source, told apart from a pygame channel by its type."""

    __slots__ = ('source',)

    def __init__(self, source):
        self.source = source


class _Anonymous(object):
    """Something Titan started that cannot be asked about afterwards.

    `play_sound_file` answers only whether it began, so a handle of this shape
    reports "finished" at once - which is the honest answer when there is
    nothing to ask, and is only ever reached when neither of the two placed
    paths worked.
    """

    __slots__ = ()


def _pitch_ratio(cents):
    """Klango's `freq`, in hundredths of a semitone, as a playback ratio."""
    return 2.0 ** (max(-2400.0, min(2400.0, float(cents or 0.0))) / 1200.0)


def _pitched(pygame, clip, cents):
    """The same sound a little higher or lower, by resampling it.

    numpy and `pygame.sndarray` are what make this cheap enough to do at all;
    without either, the sound is played at its own pitch, which loses a row of
    the board rather than the whole game.
    """
    try:
        import numpy

        ratio = _pitch_ratio(cents)
        samples = pygame.sndarray.array(clip)
        length = samples.shape[0]
        wanted = max(1, int(length / ratio))
        index = numpy.linspace(0, length - 1, wanted)
        if samples.ndim == 1:
            out = numpy.interp(index, numpy.arange(length), samples)
        else:
            out = numpy.stack(
                [numpy.interp(index, numpy.arange(length), samples[:, channel])
                 for channel in range(samples.shape[1])], axis=1)
        return pygame.sndarray.make_sound(
            numpy.ascontiguousarray(out.astype(samples.dtype)))
    except Exception:
        return None


class ClingHost(object):
    """What an engine or an application's own script is handed.

    One object, because an application should not have to reach into Cling to
    find its own texts: `host.text('welcome')` is its welcome message in the
    user's language, `host.field_sound('t_mole_hello', field)` puts its own
    sound at a place on its own board, and neither knows what Titan is.
    """

    #: The most a `http_get` will bring back. A page bigger than this is a
    #: download, and an application that wanted one should say so.
    MAX_FETCH = 2 * 1024 * 1024

    def __init__(self, app, language='', profile=None,
                 speaker=None, mixer=None, store=None, surface=None,
                 clock=None):
        from . import account as account_module
        from . import store as store_module

        self.app = app.open(language)
        self.language = language
        self.texts = self.app.texts
        self.skin = self.app.skin
        self.speaker = speaker or Speaker()
        self.mixer = mixer or Mixer()
        # The profile is the Titan-Net user name, so two people sharing one
        # Windows account keep their own saves and their own scores - and an
        # application that wants "the account" is given the one the user
        # already has, rather than being allowed to ask for another.
        self.account = account_module.whoami()
        self.store = store or store_module.Store(
            app.id, profile or self.account.profile)
        self.surface = surface
        self.clock = clock or time.monotonic
        self.messages = []        # what the surface should show, in order
        #: True once `close()` has run: the application is over, and nothing
        #: it asks for after that is answered.
        self.closed = False
        #: The emulator's sound engine, when one is running - set by
        #: `klango.engine.install`. Closing goes through it as well, because
        #: it holds sounds that have been SCHEDULED and not yet started.
        self.klango_sounds = None

    @property
    def locale(self):
        """The locale the PLATFORM runs in: Titan's, in Klango's spelling.

        Not the application's. `host.texts.locale` is the best locale that
        application actually ships, which is a different question and a worse
        answer for everything outside it: an application with only `en-us` was
        making the whole platform English on a Polish Titan - its menu, its
        Settings, its Help, the word "shortcut". Cling follows the language
        the user chose in Titan, and an application that has not been
        translated falls back on its own, which is what `TextCatalogue` is
        for.
        """
        from . import resources
        wanted = resources.normalise_locale(self.language)
        if wanted:
            return wanted
        return (self.texts.locale if self.texts else '') or 'en-us'

    # --------------------------------------------------------------- words
    def text(self, name, *values, **kwargs):
        return self.texts.text(name, *values, **kwargs)

    def say(self, text, position=0.0, pitch=0.0, interrupt=True, wait=False):
        if self.closed:
            return False
        return self.speaker.say(text, position, pitch, interrupt, wait)

    def say_text(self, name, *values, **kwargs):
        """Say one of the application's own texts, if it has it."""
        text = self.text(name, *values)
        if not text:
            return False
        return self.say(text, kwargs.get('position', 0.0),
                        kwargs.get('pitch', 0.0),
                        kwargs.get('interrupt', True),
                        kwargs.get('wait', False))

    def say_at(self, text, field, interrupt=True):
        """Say something from a place on the board."""
        if field is None:
            return self.say(text, interrupt=interrupt)
        return self.say(text, position=field.pan, pitch=field.semitones,
                        interrupt=interrupt)

    def stop_speech(self):
        self.speaker.stop()

    def show(self, text):
        """Put a line in front of the user: spoken, and on the surface."""
        text = (text or '').strip()
        if not text or self.closed:
            return
        self.messages.append(text)
        if self.surface is not None:
            try:
                self.surface.show_message(text)
            except Exception:
                pass
        self.say(text)

    # -------------------------------------------------------------- sounds
    def sound_path(self, name):
        """Where a named sound is: the application's skin, then Titan's theme.

        The fallback is what lets a Cling application ship no audio at all and
        still sound like the desktop it is running on - `host.play('ui/focus')`
        is the focus cue of whichever sound theme the user chose.  It obeys
        Settings -> Sounds -> "use the equivalent from the default theme": a
        user who turned that off has said they do not want sounds their theme
        has not got, and that answer is not a Cling application's to overrule.
        """
        path = self.skin.sound(name) if self.skin else ''
        if path:
            return path
        module = self.mixer._sound_module()
        if module is None:
            return ''
        cleaned = str(name or '').replace('\\', '/')
        head, _sep, leaf = cleaned.rpartition('/')
        for candidate_name in (leaf, leaf + '.ogg', leaf + '.wav'):
            if not candidate_name:
                continue
            try:
                found = module.feature_sound_path(head or 'ui', candidate_name)
            except Exception:
                found = ''
            if found and os.path.isfile(found):
                return found
        return ''

    def play(self, name, pan=0.0, elevation=0.0, gain=1.0, cents=0.0):
        return self.mixer.play(self.sound_path(name), pan, elevation, gain,
                               cents)

    def start(self, name, pan=0.0, elevation=0.0, gain=1.0, cents=0.0,
              loop=False):
        """The same, but handing back what is playing - see `Mixer.start`."""
        return self.mixer.start(self.sound_path(name), pan, elevation, gain,
                                cents, loop)

    def play_at(self, name, field, gain=1.0):
        """A sound at a field: its pan, its height, its distance and its
        pitch at once - which together are the whole of what makes a Klango
        board a place rather than a list."""
        if field is None:
            return self.play(name)
        return self.mixer.play(self.sound_path(name), field.pan,
                               field.elevation, gain * field.gain,
                               field.cents)

    def loop(self, name, pan=0.0, gain=0.6):
        return self.mixer.loop(self.sound_path(name), pan, gain)

    def sound_busy(self, handle):
        return self.mixer.busy(handle)

    def sound_velocity(self, handle, velocity):
        return self.mixer.set_velocity(handle, velocity)

    def pause_sound(self, handle, paused=True):
        return self.mixer.pause(handle, paused)

    def stop_sound(self, handle):
        self.mixer.stop(handle)

    def stop_sounds(self):
        self.mixer.stop_all()

    # ------------------------------------------------------------- the run
    def now(self):
        return self.clock()

    # ---------------------------------------------------------- the world
    def http_get(self, url, timeout=8.0):
        """Fetch a page for an application that is a client for something.

        Klango's Wikipedia browser, its translator and its shops are all this
        shape, so an application must be able to reach the network - and must
        be able to do exactly that and nothing more.  Only `https` and `http`,
        only GET, a timeout that cannot be raised past a minute, and a ceiling
        on how much comes back, so a page that is really a firehose cannot
        take the desktop's memory with it.  Answers ('', reason) rather than
        raising: an application that cannot reach the network is one that says
        so, not one that stops.
        """
        url = str(url or '').strip()
        if not url.lower().startswith(('http://', 'https://')):
            return '', 'only http and https addresses can be fetched'
        try:
            import requests
        except Exception as error:
            return '', 'this build cannot reach the network: %s' % error
        try:
            response = requests.get(
                url, timeout=max(1.0, min(60.0, float(timeout))),
                headers={'User-Agent': 'Titan-Cling/1.0'}, stream=True)
            body = response.raw.read(self.MAX_FETCH + 1, decode_content=True)
        except Exception as error:
            return '', str(error)
        if len(body) > self.MAX_FETCH:
            return '', 'that page is larger than Cling will fetch'
        encoding = response.encoding or 'utf-8'
        try:
            return body.decode(encoding, 'replace'), ''
        except (LookupError, UnicodeDecodeError):
            return body.decode('utf-8', 'replace'), ''

    def ask(self, prompt, default=''):
        """Ask the player for a line of text. '' when they said nothing.

        A window is the only way to take typing, so this is the one place the
        host touches wx - and it does it through the surface, on the GUI
        thread, so an application with no window (a test, an action) simply
        gets the default back instead of hanging on a dialog nobody can see.
        """
        if self.surface is None:
            return default
        try:
            import wx
        except Exception:
            return default
        answer = {'value': default}

        def show():
            dialog = wx.TextEntryDialog(self.surface, str(prompt or ''),
                                        self.app.name(self.language),
                                        str(default or ''))
            try:
                if dialog.ShowModal() == wx.ID_OK:
                    answer['value'] = dialog.GetValue()
            finally:
                dialog.Destroy()

        if wx.IsMainThread():
            show()
        else:
            wx.CallAfter(show)
        return answer['value']

    # ------------------------------------------------------------- account
    def whoami(self):
        """The account this application is playing under."""
        return self.account

    def sign_in(self):
        """(account, error) - for an application that really needs one."""
        from . import account as account_module
        self.account, error = account_module.sign_in()
        return self.account, error

    def publish_score(self, points, extra=None):
        """Put a score on this application's shared Titan-Net table.

        Best effort by design: the score is already in the player's own store
        before this is called, so a server that is not there costs a sentence
        and never a game.
        """
        from . import account as account_module
        return account_module.publish_score(self.app.id, points, extra)

    def leaderboard(self, limit=10):
        from . import account as account_module
        return account_module.leaderboard(self.app.id, limit)

    def close(self):
        """Give everything back. Called however the application is left.

        Closing the window has to make the application stop MAKING SOUND
        immediately, whether or not its own thread has noticed yet: an
        emulated application runs on a thread of its own, is a frame or two
        behind at best, and may be inside a Lua call that will not return for
        a moment. So the speaker and the mixer are shut rather than merely
        stopped - what is playing stops, and nothing new starts, however late
        it is asked for.
        """
        if self.closed:
            return
        self.closed = True
        for shut in (self.klango_sounds, self.speaker, self.mixer):
            if shut is None:
                continue
            try:
                closer = getattr(shut, 'close', None) or getattr(shut, 'stop_all')
                closer()
            except Exception:
                pass
