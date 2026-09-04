# -*- coding: utf-8 -*-
"""The sound engine Klango's library drives, over Titan's mixer.

A Klango application is not drawn, it is heard, so this is the piece that
decides whether an emulated one is playable at all.  It is written from what
`llib_snd.lua` actually does, and each of these is something Cling used to
answer with a constant - every one of which made a real game unplayable:

- **a sequence is a list of sounds with DELAYS**, scheduled by
  `_Snd_Create(name, spec, {delay = seconds})`.  Ignoring the third argument
  played a whole menu at once: three announcements inside forty milliseconds,
  which is a noise rather than a menu.
- **the delays are computed from how long each sample IS**
  (`_Snd_GetProperty(name, "sampleTime")`), so a length of zero collapses the
  schedule before it is even built.
- **a group is what the library holds on to.**  `k_SoundPlay` puts a sequence
  in a group of its own and hands back the GROUP id; `k_SoundIsPlaying` and
  `k_SoundStop` are then asked about that id, not about a sound.  A
  `_Snd_GroupCreate` that answers 1 every time means every sequence in the
  program is the same one.
- **`play` is a repeat count**, not a boolean: 0 once, -1 for ever (a level's
  background music, a dialog's bed), n for n+1 times.
- **`pos3d` and `freq` are where the sound is** - see `engine._placement`.

Nothing here starts a thread.  A delayed sound is started by `pump()`, which
runs once per frame from `_Sys_BeginFrame`: the platform's own heartbeat, at
60 Hz, which is finer than any delay a Klango sequence uses and costs nothing
when there is nothing due.
"""

import os

from ..lua.runtime import LuaTable

#: Group ids and sound ids share one namespace as far as `_Snd_IsPlaying` is
#: concerned - it is handed whichever the caller has - so they are told apart
#: by size. Groups are small because the library's four live for the whole run
#: and are compared by value.
FIRST_SOUND = 1000001

#: How many frames apart the empty groups are swept up. `k_SoundPlay` makes a
#: group per sequence and never destroys one, so something has to.
TIDY_EVERY = 120


class Sample(object):
    """A sound the application has named: a file, or something to say.

    `near` and `far` are Klango's `dmin`/`dmax`, given when the sample is
    PREPARED and not when it is played - they are a property of the sound,
    and applications set them very differently: Skeet's clay pigeon is
    `dmin=1, dmax=10` and flies from twenty units away, while the platform's
    own speech is `dmin=1, dmax=3`. Using one figure for both makes the wide
    one sound flat and the near one sound distant.
    """

    __slots__ = ('name', 'path', 'text', 'length', 'near', 'far')

    def __init__(self, name, path='', text='', length=0.0, near=1.0, far=3.0):
        self.name = name
        self.path = path
        self.text = text
        self.length = length
        self.near = float(near)
        self.far = max(float(far), float(near) + 0.001)


class Playing(object):
    """One sound on its way to being heard, or being heard."""

    __slots__ = ('identifier', 'sample', 'group', 'start_at', 'stop_at',
                 'place', 'handle', 'started', 'stopped', 'journey',
                 'paused', 'held_at')

    def __init__(self, identifier, sample, group, start_at, place):
        self.identifier = identifier
        self.sample = sample
        self.group = group
        self.start_at = start_at
        self.stop_at = 0.0
        self.place = place
        self.handle = None
        self.started = False
        self.stopped = False
        #: Where it is travelling: (from, to, seconds, began). A Klango
        #: sound can be given a path across the listener while it plays.
        self.journey = None
        #: Held where it is by `_Snd_Action(gid, {pause = 1})`, which every
        #: dialog does to the game's own group. A paused sound has not
        #: finished, so it is still what `k_SoundIsPlaying` answers about.
        self.paused = False
        #: When it was last seen held, so a journey can be given the time
        #: back that it spent paused.
        self.held_at = 0.0


class SoundBank(object):
    """`_Snd_*`, as Klango's library uses it."""

    def __init__(self, host, filesystem, speaking, resolve):
        self.host = host
        self.filesystem = filesystem
        self.speaking = speaking
        self.resolve = resolve
        self.samples = {}
        self.playing = {}
        self.groups = {}
        #: A group's own volume, as `_Snd_Action(gid, ...)` sets it:
        #: `{'vol': .., 'mul': .., 'slide': (from, to, seconds, began)}`.
        #: Klango ducks whole groups rather than sounds - the ambience while
        #: a dialog is up, the background fading in when a game starts - and
        #: the multiplier has to outlive the sounds that were playing when it
        #: was set, because the next sound STARTED in that group is ducked
        #: too.
        self.group_gain = {}
        #: Which group each was created inside. Klango's groups are a tree.
        self.group_parent = {}
        #: The other way down the same tree, so a subtree is a walk rather
        #: than a sweep of every group there has ever been.
        self.group_children = {}
        #: Frames since the last sweep of the empty groups.
        self._tidy = 0
        self.active_group = 0
        self._next_group = 0
        self._next_sound = FIRST_SOUND
        #: True once the application has been closed. A Klango application
        #: runs on a thread of its own and is a frame or two behind, so what
        #: it asks for after that must not be answered - a sound started
        #: after the window closed is a sound nothing will ever stop.
        self.closed = False

    # -------------------------------------------------------------- naming
    def load(self, name, source=None, options=None):
        """`_Snd_Load(name, file, args)` - name a sample.

        The NAME comes first and the file second, which is the opposite way
        round from how it reads; `k_VoiceSpeak` passes a rendered stream as
        the file, and an application passes the same string twice.

        `args` carries `dmin`/`dmax` - how a sound fades with distance - and
        they belong to the SAMPLE, which is why they are remembered here and
        not read again at every play.
        """
        key = _key(name)
        if not key:
            return None
        said = _speech_note(source)
        if said:
            sample = Sample(key, text=said,
                            length=self.speaking.seconds(said))
        else:
            wanted = source if isinstance(source, str) and source else key
            sample = self._sample(key, wanted)
        near, far = _distance_model(options)
        if near is not None:
            sample.near, sample.far = near, far
        self.samples[key] = sample
        return 1

    def _sample(self, key, wanted):
        """What a name really is: text to say, or a file to play.

        Two of Klango's own conventions decide this, and both are the
        difference between an application that talks and one that does not:

        - **`*text`** is text for the synthesiser rather than a file. It is how
          the platform says anything an application shipped no recording for.
        - **a `.txt` where a sample was asked for is text too.** Klango's own
          `speechexts` is `.wav .ogg .spx .txt .mp3` - a *text file among the
          sound formats* - and its engine synthesises one. So a menu item
          named `/lang/en-us/default/new_game`, in an application that ships
          only `new_game.txt`, is the words in that file. Without this the
          whole menu of every application is silent: the earcons play, the
          items say nothing, and there is no way to tell what is selected.
        """
        text = _spoken(wanted) or _spoken(key)
        if text:
            return Sample(key, text=text,
                          length=self.speaking.seconds(text))
        path = self.resolve(wanted) or self.resolve(key)
        if path and path.lower().endswith('.txt'):
            said = _read(path)
            return Sample(key, text=said, length=self.speaking.seconds(said))
        return Sample(key, path=path, length=self._length(path))

    def _length(self, path):
        if not path:
            return 0.0
        try:
            return float(self.host.mixer.length(path))
        except Exception:
            return 0.0

    def sample_for(self, name):
        """The sample a call names, registering it if it has not been."""
        key = _key(name)
        if not key:
            return None
        found = self.samples.get(key)
        if found is None:
            found = self._sample(key, key)
            self.samples[key] = found
        return found

    def is_loaded(self, name):
        return _key(name) in self.samples

    def unload(self, name):
        key = _key(name)
        for sound in list(self.playing.values()):
            if sound.sample is not None and sound.sample.name == key:
                self.stop_sound(sound)
        return self.samples.pop(key, None) is not None

    def property_of(self, name, what=None):
        """`_Snd_GetProperty`. `sampleTime` is a length in seconds.

        It is what a sequence's delays are computed from, so answering 0 puts
        every element of a sequence at the same moment.
        """
        sample = self.sample_for(name)
        if sample is None:
            return 0
        if str(what or '').lower() in ('sampletime', 'length', 'time'):
            return sample.length
        return 0

    # -------------------------------------------------------------- groups
    def group_create(self, _size=None):
        """`_Snd_GroupCreate` - a group INSIDE whichever one is active.

        Klango's groups are a tree, and every `k_SoundPlay` makes one: it
        creates a group, plays the sequence in it and puts the old one back
        (`llib_snd.lua`). So the ambience group holds no sounds of its own at
        all - it holds the group `k_SoundPlay` made under it - and ducking it
        by looking only at sounds whose group id IS the ambience reached
        nothing. Nothing about the volume worked until the tree did.
        """
        self._next_group += 1
        self.groups[self._next_group] = []
        self.group_parent[self._next_group] = self.active_group
        self.group_children.setdefault(self.active_group, set()).add(
            self._next_group)
        return self._next_group

    def _descendants(self, group):
        """A group and everything created inside it.

        Walked down `group_children` rather than by sweeping every group
        looking for one whose parent is in the set: a group is made for every
        `k_SoundPlay`, so a long game has thousands of them and the sweep was
        quadratic in a method `pump()` calls while a fade is running.
        """
        found = {group}
        queue = [group]
        while queue:
            for child in self.group_children.get(queue.pop(), ()):
                if child not in found:
                    found.add(child)
                    queue.append(child)
        return found

    def _ancestry(self, group):
        """A group and the groups it was created inside, outwards."""
        chain, seen = [], set()
        while group and group not in seen:
            chain.append(group)
            seen.add(group)
            group = self.group_parent.get(group, 0)
        # Group 0 is the master, and it is the root of every chain: Klango
        # addresses the listener and the whole mixer through it.
        chain.append(0)
        return chain

    def group_destroy(self, group=None):
        identifier = _int(group)
        for sound in self.of_group(identifier):
            self.stop_sound(sound)
        for child in self._descendants(identifier):
            self._forget_group(child)
        return True

    def _forget_group(self, group):
        self.groups.pop(group, None)
        self.group_gain.pop(group, None)
        self.group_children.pop(group, None)
        parent = self.group_parent.pop(group, None)
        if parent is not None:
            self.group_children.get(parent, set()).discard(group)

    def _tidy_groups(self):
        """Forget the groups `k_SoundPlay` made and nothing is left in.

        The library creates one per sequence and never destroys it, so a game
        played for an hour would otherwise accumulate tens of thousands of
        empty groups - all of them walked whenever a parent is ducked.
        """
        busy = {sound.group for sound in self.playing.values()}
        busy.update(self._ancestry(self.active_group))
        for group in list(self.groups):
            if group in busy or self.group_children.get(group):
                continue
            if self.group_gain.get(group):
                continue
            self._forget_group(group)

    def group_set_active(self, group=None):
        previous = self.active_group
        self.active_group = _int(group)
        return previous

    def group_factor(self, group):
        """What a group's volume comes to right now, its parents included."""
        factor = 1.0
        for step in self._ancestry(group):
            entry = self.group_gain.get(step)
            if not entry:
                continue
            multiplier = entry['mul']
            slide = entry.get('slide')
            if slide:
                first, last, seconds, began = slide
                through = 1.0 if seconds <= 0 else \
                    min(1.0, max(0.0, (self.host.now() - began) / seconds))
                multiplier = first + (last - first) * through
            factor *= entry['vol'] * multiplier
        return max(0.0, min(1.0, factor))

    def _apply_group(self, group):
        """Put a group's volume onto everything playing in it."""
        factor = self.group_factor(group)
        for sound in self.of_group(group):
            if sound.handle is None:
                continue
            self.host.mixer.set_gain(sound.handle, sound.place['pan'],
                                     max(0.0, min(1.0,
                                                  sound.place['gain'] * factor)),
                                     sound.place.get('elevation', 0.0))

    def of_group(self, group):
        if not group:
            # 0 and 1 are the library's "everything": the master volume and
            # the stop-the-world it does when it shuts down.
            return list(self.playing.values())
        inside = self._descendants(group)
        return [sound for sound in self.playing.values()
                if sound.group in inside]

    # ------------------------------------------------------------- playing
    def create(self, name=None, options=None, when=None):
        """`_Snd_Create(name, spec, when)` - play it, now or in a moment."""
        if self.closed:
            return 0
        sample = self.sample_for(name)
        if sample is None or (not sample.path and not sample.text):
            return 0
        from .engine import _placement

        place = _placement(options, sample)
        delay = _delay(when)
        self._next_sound += 1
        sound = Playing(self._next_sound, sample, self.active_group,
                        self.host.now() + delay, place)
        end = _end_time(when)
        if end:
            sound.stop_at = sound.start_at + end
        self.playing[sound.identifier] = sound
        if delay <= 0:
            self._begin(sound)
        return sound.identifier

    def _begin(self, sound):
        sound.started = True
        place = sound.place
        if sound.sample.text:
            self.host.say(sound.sample.text, position=place['pan'],
                          pitch=max(-10.0, min(10.0, place['cents'] / 100.0)))
            self.speaking.started(sound.identifier, sound.sample.text)
            return
        if not sound.sample.path:
            return
        gain = place['gain'] * self.group_factor(sound.group)
        sound.handle = self.host.mixer.start(
            sound.sample.path, place['pan'], place['elevation'],
            max(0.0, min(1.0, gain)), place['cents'], place['loop'],
            place['repeats'])
        if place.get('velocity') and sound.handle is not None:
            self.host.mixer.set_velocity(sound.handle, place['velocity'])
        if place.get('to') and sound.handle is not None:
            self._send_on_its_way(sound, place)

    def _send_on_its_way(self, sound, place):
        """A sound that TRAVELS while it plays.

        `pos3dSlide = {from, to, seconds}` is how Skeet throws a clay pigeon:
        the disc really crosses the listener from twenty units left to twenty
        right, and aiming at it is the game. It is stepped by the FRAME - the
        same clock everything else here runs on - rather than by a thread of
        its own, so a game that is paused pauses the flight with it.
        """
        sound.journey = (place['at'], place['to'],
                         max(0.05, float(place.get('seconds') or 0.0)),
                         self.host.now())

    def _step_journey(self, sound, now):
        """Move a travelling sound to where it has got to."""
        start, end, seconds, began = sound.journey
        through = min(1.0, max(0.0, (now - began) / seconds))
        where = tuple(start[axis] + (end[axis] - start[axis]) * through
                      for axis in range(3))
        from .engine import _pan_of, _distance_gain, _elevation_of

        sound.place['pan'] = _pan_of(where[0], where[1])
        sound.place['gain'] = _distance_gain(*where, sample=sound.sample)
        # The height moves with it: `pos3dSlide` is a place, not a pan, and a
        # disc thrown across the listener is re-placed rather than re-mixed.
        sound.place['elevation'] = _elevation_of(*where)
        self.host.mixer.set_gain(
            sound.handle, sound.place['pan'],
            max(0.0, min(1.0, sound.place['gain']
                         * self.group_factor(sound.group))),
            sound.place['elevation'])
        if through >= 1.0:
            sound.journey = None

    def pump(self):
        """Start what is due and forget what has finished. Once per frame."""
        if self.closed:
            return
        now = self.host.now()
        for group, entry in list(self.group_gain.items()):
            slide = entry.get('slide')
            if not slide:
                continue
            self._apply_group(group)
            first, last, seconds, began = slide
            if now - began >= seconds:
                entry['mul'], entry['slide'] = last, None
        self._tidy += 1
        if self._tidy >= TIDY_EVERY:
            self._tidy = 0
            self._tidy_groups()
        for identifier in list(self.playing):
            sound = self.playing.get(identifier)
            if sound is None:
                continue
            if not sound.started:
                if now >= sound.start_at:
                    self._begin(sound)
                continue
            if sound.stop_at and now >= sound.stop_at:
                self.stop_sound(sound)
                continue
            if sound.paused:
                # Time does not pass for a held sound: a clay pigeon paused
                # under a dialog must be where it was when the dialog goes.
                if sound.journey is not None:
                    start, end, seconds, began = sound.journey
                    sound.journey = (start, end, seconds,
                                     began + (now - sound.held_at))
                sound.held_at = now
                continue
            if sound.journey is not None:
                self._step_journey(sound, now)
            if not self._audible(sound):
                self.playing.pop(identifier, None)
                self.speaking.finished(identifier)

    def _audible(self, sound):
        if sound.stopped:
            return False
        if sound.paused:
            # Held, not finished: a dialog pauses the game's whole group and
            # the game asks about its own sounds again when it comes back.
            return True
        if sound.journey is not None:
            # A sound that is still crossing the listener has not finished,
            # whatever the mixer thinks of the clip: the journey IS the
            # sound as far as the application is concerned, and forgetting
            # it half way leaves the clay pigeon hanging where it was.
            return True
        if sound.sample.text:
            return self.speaking.busy(sound.identifier)
        if sound.handle is not None:
            return self.host.mixer.busy(sound.handle)
        return False

    def is_playing(self, target=None):
        """`_Snd_IsPlaying`, asked about a sound, a group OR a name.

        The library asks about a GROUP - `k_SoundPlay` hands one back and its
        sequences poll it - so this has to understand all three.
        """
        if isinstance(target, str):
            key = _key(target)
            return any(sound.sample is not None and sound.sample.name == key
                       and self._alive(sound)
                       for sound in self.playing.values())
        identifier = _int(target)
        if identifier >= FIRST_SOUND:
            sound = self.playing.get(identifier)
            return bool(sound and self._alive(sound))
        return any(self._alive(sound) for sound in self.of_group(identifier))

    def _alive(self, sound):
        """Scheduled counts as playing: it has not had its turn yet."""
        if sound.stopped:
            return False
        if not sound.started:
            return True
        return self._audible(sound)

    def action(self, target=None, what=None, when=None):
        """`_Snd_Action` - stop it, or change its volume."""
        if not isinstance(what, LuaTable):
            return True
        sounds = self._targets(target)
        stopping = what.raw_get('stop')
        volume = what.raw_get('vol')
        multiplier = what.raw_get('volMul')
        slide = what.raw_get('volMulSlide')
        pausing = what.raw_get('pause')
        resuming = what.raw_get('resume')
        end = _end_time(when)
        # `pause` and `resume` are how the platform gets out of the way. Every
        # dialog pauses the GAME group and ducks the ambience to a fifth
        # (`_Snd_Action(gid, {pause = 1, volMul = 0})`), and puts both back
        # when it closes. Ignoring them meant a splash over a running game had
        # the game still going on underneath it, at full volume, over the
        # words - which is most of what "the sounds are wrong" sounds like.
        if pausing is not None or resuming is not None:
            paused = pausing is not None and _int(pausing) != 0
            for sound in sounds:
                if paused and not sound.paused:
                    sound.held_at = self.host.now()
                sound.paused = paused
                if sound.handle is not None:
                    self.host.mixer.pause(sound.handle, paused)
        # A GROUP is ducked as a group. `k_BackgroundPlay` fades the ambience
        # in with `volMulSlide = {0, 1, speed}` and every dialog ducks it back
        # down with `k_BackgroundVolumeSlideTo`; ignoring the slide left the
        # background at one volume for the whole run, over dialogs, menus and
        # the game alike - and `volMul = 0` (which is how the fade-in starts)
        # would have silenced it for ever had it been read as a sound's own.
        if _int(target) < FIRST_SOUND and (volume is not None
                                           or multiplier is not None
                                           or isinstance(slide, LuaTable)):
            group = _int(target)
            entry = self.group_gain.setdefault(
                group, {'vol': 1.0, 'mul': 1.0, 'slide': None})
            if volume is not None:
                entry['vol'] = max(0.0, min(1.0, _float(volume)))
            if multiplier is not None:
                entry['mul'] = max(0.0, min(1.0, _float(multiplier)))
                entry['slide'] = None
            if isinstance(slide, LuaTable):
                first = _float(slide.raw_get(1))
                last = _float(slide.raw_get(2))
                seconds = max(0.0, _float(slide.raw_get(3)))
                if seconds <= 0:
                    entry['mul'], entry['slide'] = last, None
                else:
                    entry['slide'] = (first, last, seconds, self.host.now())
            self._apply_group(group)
            return True
        # Skeet throws its clay pigeon and only THEN sets it moving, with
        # `k_SoundAction(sid, {pos3dSlide = {...}})` on the sound that is
        # already playing. Ignoring it left every disc where it was thrown
        # from, which is a game with nothing to aim at.
        from .engine import _placement

        travel = _placement(what, sounds[0].sample if sounds else None)
        if travel.get('velocity'):
            for sound in sounds:
                sound.place['velocity'] = travel['velocity']
                if sound.handle is not None:
                    self.host.mixer.set_velocity(sound.handle,
                                                 travel['velocity'])
        if travel.get('to'):
            for sound in sounds:
                if sound.handle is not None or not sound.started:
                    sound.place.update(travel)
                    self._send_on_its_way(sound, travel)
            return True
        for sound in sounds:
            if stopping is not None:
                if end:
                    sound.stop_at = self.host.now() + end
                else:
                    self.stop_sound(sound)
                continue
            if volume is not None or multiplier is not None:
                gain = sound.place['gain']
                if volume is not None:
                    gain = _float(volume)
                if multiplier is not None:
                    gain *= _float(multiplier)
                sound.place['gain'] = max(0.0, min(1.0, gain))
                self.host.mixer.set_gain(
                    sound.handle, sound.place['pan'],
                    max(0.0, min(1.0, sound.place['gain']
                                 * self.group_factor(sound.group))),
                    sound.place.get('elevation', 0.0))
        return True

    def _targets(self, target):
        if isinstance(target, str):
            key = _key(target)
            return [sound for sound in self.playing.values()
                    if sound.sample is not None and sound.sample.name == key]
        identifier = _int(target)
        if identifier >= FIRST_SOUND:
            sound = self.playing.get(identifier)
            return [sound] if sound is not None else []
        return self.of_group(identifier)

    def stop_sound(self, sound):
        sound.stopped = True
        if sound.handle is not None:
            self.host.stop_sound(sound.handle)
        if sound.sample is not None and sound.sample.text:
            self.speaking.finished(sound.identifier)
            self.host.stop_speech()
        self.playing.pop(sound.identifier, None)

    def stop_all(self):
        """Everything this application has playing, and everything it has
        scheduled and not yet played."""
        self.closed = True
        for sound in list(self.playing.values()):
            self.stop_sound(sound)
        self.playing = {}
        self.host.stop_sounds()
        return True

    def close(self):
        """The application is over. `stop_all` and stay stopped."""
        return self.stop_all()


# ------------------------------------------------------------------ pieces
def _key(name):
    """What a sample is called. Klango names one with a path and no extension."""
    if isinstance(name, LuaTable):
        first = name.raw_get(1)
        return _key(first) if first is not None else ''
    if isinstance(name, (int, float)) and not isinstance(name, bool):
        return str(int(name))
    return str(name or '')


def _spoken(value):
    """Klango's `*text` - a sample name beginning with `*` is text to SAY.

    It is how the platform says anything an application shipped no recording
    for, which is most of what an application says.
    """
    text = value if isinstance(value, str) else ''
    return text[1:].strip() if text.startswith('*') else ''


def _delay(when):
    if isinstance(when, LuaTable):
        return max(0.0, _float(when.raw_get('delay')))
    return 0.0


def _end_time(when):
    if isinstance(when, LuaTable):
        moment = when.raw_get('sampleTime')
        if isinstance(moment, LuaTable):
            return max(0.0, _float(moment.raw_get(1)))
    return 0.0


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _read(path):
    """The words in a text sample. Klango's own `k_ReadFile`, in Python."""
    from .. import textio
    return textio.read(path).strip()


def _speech_note(source):
    """The words a `_Voice_SpeakToStream` note is carrying, or ''."""
    if not isinstance(source, LuaTable):
        return ''
    from .engine import SPEECH_STREAM
    return str(source.raw_get(SPEECH_STREAM) or '')


def _distance_model(options):
    """Klango's `dmin`/`dmax` for a sample, or (None, None)."""
    if not isinstance(options, LuaTable):
        return None, None
    near = options.raw_get('dmin')
    far = options.raw_get('dmax')
    if near is None and far is None:
        return None, None
    near = _float(near) if near is not None else _float(far) / 2.0
    far = _float(far) if far is not None else near * 2.0
    return max(0.01, near), max(0.02, far)
