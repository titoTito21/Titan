# -*- coding: utf-8 -*-
"""A place made of sound, described by the application and walked through.

Klango's soundscapes ship a `spec.txt`, and it is a complete specification of
the place - so complete that the engine below has nothing of its own to decide:

    start : glowny                  where the listener begins
    Location : glowny               a place
        BkgVolume : 0.9             how loud its background recording is
        links : burta, rufa         where you can go from here
        fx : g1                     something that happens here, now and then
            fxangle     : 300, 60   from somewhere in this arc
            fxdist      : 1, 1      at this distance
            fxtimestart : 1, 120    first, somewhere in these seconds
            fxtimedelta : 120, 240  then again, every so often
            fxvol       : 0.3, 0.8  this loud

Which is why Zawisza Czarny - a soundscape of a Polish tall ship, with the
watch bells, the sails and the crew each in their own arc around the listener -
runs here without a line of its own code: the recordings are the ship and the
specification is where they are.

An application with sounds but no `spec.txt` still opens: its sounds become one
place, spread across the stereo image, which is the honest reading of a folder
of recordings with nothing said about them.
"""

import math
import os
import random

from .base import Engine
from .. import topology as topology_module

_SOUND_SUFFIXES = ('.ogg', '.wav', '.mp3', '.flac')
SPEC_FILE = 'spec.txt'


class Effect(object):
    """Something that happens in a place, now and then, from a direction."""

    __slots__ = ('name', 'angle', 'distance', 'first', 'gap', 'volume', 'due')

    def __init__(self, name, angle, distance, first, gap, volume):
        self.name = name
        self.angle = angle          # (from, to) degrees, 0 = ahead, 90 = right
        self.distance = distance
        self.first = first
        self.gap = gap
        self.volume = volume
        self.due = 0.0

    def schedule(self, now, generator, initial=False):
        low, high = self.first if initial else self.gap
        self.due = now + generator.uniform(min(low, high), max(low, high))


class Location(object):
    """One place: its background, the ways out of it, and what happens in it."""

    __slots__ = ('name', 'background_volume', 'links', 'effects')

    def __init__(self, name):
        self.name = name
        self.background_volume = 0.8
        self.links = []
        self.effects = []


def parse_spec(text):
    """`spec.txt` as (start, {name: Location}). Never raises on a bad line."""
    start = ''
    locations = {}
    current = None
    effect = None
    for raw in text.replace('\r\n', '\n').split('\n'):
        line = raw.strip()
        if not line or line.startswith('--') or line.startswith('#'):
            continue
        if ':' not in line:
            continue
        key, _sep, value = line.partition(':')
        key = key.strip().lower()
        value = value.strip()
        if key == 'start':
            start = value
        elif key == 'location':
            current = Location(value)
            locations[value] = current
            effect = None
        elif current is None:
            continue
        elif key == 'bkgvolume':
            current.background_volume = _one(value, 0.8)
        elif key == 'links':
            current.links = [part.strip() for part in value.split(',')
                             if part.strip()]
        elif key == 'fx':
            effect = Effect(value, (0.0, 360.0), (1.0, 1.0), (5.0, 30.0),
                            (30.0, 90.0), (0.5, 0.8))
            current.effects.append(effect)
        elif effect is not None and key in ('fxangle', 'fxdist', 'fxtimestart',
                                            'fxtimedelta', 'fxvol'):
            pair = _pair(value)
            if key == 'fxangle':
                effect.angle = pair
            elif key == 'fxdist':
                effect.distance = pair
            elif key == 'fxtimestart':
                effect.first = pair
            elif key == 'fxtimedelta':
                effect.gap = pair
            else:
                effect.volume = pair
    if not start and locations:
        start = next(iter(locations))
    return start, locations


def _pair(value):
    parts = [part.strip() for part in value.split(',') if part.strip()]
    numbers = []
    for part in parts[:2]:
        numbers.append(_one(part, 0.0))
    if not numbers:
        return (0.0, 0.0)
    if len(numbers) == 1:
        return (numbers[0], numbers[0])
    return (numbers[0], numbers[1])


def _one(value, default):
    try:
        return float(str(value).replace(',', '.').strip())
    except (TypeError, ValueError):
        return default


class SoundscapeEngine(Engine):
    LABEL = 'soundscape'

    #: The names a background recording is looked for under.
    AMBIENCE = ('t_background', 'background', 'ambience', 'atmo', 'loop')

    def __init__(self, host, seed=None):
        Engine.__init__(self, host)
        self.random = random.Random(seed)
        self.start_name = ''
        self.locations = {}
        self.location = None
        self.link_index = 0
        self._background = None
        # The fallback shape, when there is no specification at all.
        self.sounds = []
        self.board = None
        self.index = 0

    # ------------------------------------------------------------- opening
    def start(self):
        self.running = True
        spec = _read_spec(self.host.app.path)
        if spec:
            self.start_name, self.locations = parse_spec(spec)
        welcome = self.host.text('welcome') or self.host.text('intro')
        self.host.show(welcome or self.host.app.name(self.host.language))
        if self.locations:
            self.enter(self.start_name)
            return
        self._start_plain()

    def _start_plain(self):
        catalogue = self.host.skin.sounds() if self.host.skin else {}
        catalogue.update(_folder_sounds(os.path.join(self.host.app.path, 'data')))
        ambience = ''
        for candidate in self.AMBIENCE:
            if candidate in catalogue:
                ambience = candidate
                break
        self.sounds = [(name, path) for name, path in sorted(catalogue.items())
                       if name != ambience]
        if not self.sounds and not ambience:
            self.host.show(self.host.text(
                'no_sounds', default='This application ships no sounds.'))
            self.finished_reason = 'no sounds'
            return
        self.board = topology_module.Board.grid(max(1, len(self.sounds)), 1)
        if ambience:
            self._background = self.host.loop(ambience, gain=0.5)
        if self.sounds:
            self._announce_plain()

    # ----------------------------------------------------------- locations
    def enter(self, name):
        location = self.locations.get(name)
        if location is None:
            self.host.show(self.host.text(
                'no_location', default='There is nowhere called %s.') % name
                if '%s' in self.host.text('no_location', default='%s')
                else name)
            return False
        self._quieten()
        self.location = location
        self.link_index = 0
        path = self._sound_path('%s_bkg' % location.name)
        if path:
            self._background = self.host.mixer.loop(
                path, 0.0, location.background_volume)
        now = self.host.now()
        for effect in location.effects:
            effect.schedule(now, self.random, initial=True)
        self.host.show(self.host.text('%s_name' % location.name,
                                      default=location.name))
        comment = self.host.text('%s_comment' % location.name)
        if comment:
            self.host.show(comment)
        self.announce_link()
        return True

    def announce_link(self):
        if not self.location or not self.location.links:
            return
        name = self.location.links[self.link_index]
        self.host.say('%s (%d/%d)' % (
            self.host.text('%s_name' % name, default=name),
            self.link_index + 1, len(self.location.links)))

    # ---------------------------------------------------------------- time
    def tick(self, now=None):
        if not self.running or self.location is None:
            return
        now = self.host.now() if now is None else now
        for effect in self.location.effects:
            if now < effect.due:
                continue
            self._fire(effect)
            effect.schedule(now, self.random)

    def _fire(self, effect):
        path = self._sound_path(effect.name)
        if not path:
            return
        low, high = effect.angle
        # An arc written `300, 60` crosses the front of the listener; taking it
        # the short way round is what the author meant, and taking it the long
        # way would put the sound exactly where it is not.
        if low > high:
            high += 360.0
        angle = self.random.uniform(low, high) % 360.0
        volume = self.random.uniform(min(effect.volume), max(effect.volume))
        distance = max(0.2, self.random.uniform(min(effect.distance),
                                                max(effect.distance)))
        # Stereo cannot tell ahead from behind, so `sin` is the whole of what
        # a pan can carry; with 3D audio on, Titan's own HRTF does the rest.
        pan = math.sin(math.radians(angle))
        self.host.mixer.play(path, pan, 0.0, volume / distance)

    # --------------------------------------------------------------- input
    def key(self, name, modifiers=()):
        name = (name or '').lower()
        if name == 'escape':
            self.stop()
            return True
        if self.location is not None:
            return self._key_in_location(name)
        return self._key_plain(name)

    def _key_in_location(self, name):
        links = self.location.links
        if name in ('left', 'up') and links:
            self.link_index = (self.link_index - 1) % len(links)
            self.announce_link()
            return True
        if name in ('right', 'down') and links:
            self.link_index = (self.link_index + 1) % len(links)
            self.announce_link()
            return True
        if name == 'enter' and links:
            self.enter(links[self.link_index])
            return True
        if name == 'space':
            self.host.show(self.host.text('%s_name' % self.location.name,
                                          default=self.location.name))
            comment = self.host.text('%s_comment' % self.location.name)
            if comment:
                self.host.show(comment)
            return True
        return False

    def _key_plain(self, name):
        if not self.sounds:
            return False
        if name in ('left', 'up'):
            self.index = (self.index - 1) % len(self.sounds)
            self._announce_plain()
            return True
        if name in ('right', 'down'):
            self.index = (self.index + 1) % len(self.sounds)
            self._announce_plain()
            return True
        if name in ('enter', 'space'):
            self.host.mixer.play(self.sounds[self.index][1],
                                 self._field().pan, self._field().elevation, 1.0)
            return True
        return False

    def _announce_plain(self):
        name, path = self.sounds[self.index]
        field = self._field()
        self.host.say_at(_pretty(name), field)
        self.host.mixer.play(path, field.pan, field.elevation, 0.7 * field.gain)

    def _field(self):
        return self.board.by_index(min(len(self.board), self.index + 1))

    # ------------------------------------------------------------- reading
    def status(self):
        if self.location is not None:
            return self.host.text('%s_name' % self.location.name,
                                  default=self.location.name)
        if self.sounds:
            return '%s (%d/%d)' % (_pretty(self.sounds[self.index][0]),
                                   self.index + 1, len(self.sounds))
        return ''

    def rows(self):
        if self.location is not None:
            return [self.host.text('%s_name' % name, default=name)
                    for name in self.location.links]
        return [_pretty(name) for name, _path in self.sounds]

    # ------------------------------------------------------------- helpers
    def _sound_path(self, name):
        for folder in (os.path.join(self.host.app.path, 'data'),
                       self.host.app.path):
            for suffix in _SOUND_SUFFIXES:
                candidate = os.path.join(folder, name + suffix)
                if os.path.isfile(candidate):
                    return candidate
        return self.host.sound_path(name)

    def _quieten(self):
        if self._background is not None:
            self.host.stop_sound(self._background)
            self._background = None

    def stop(self):
        self._quieten()
        Engine.stop(self)


def _read_spec(root):
    path = os.path.join(root, SPEC_FILE)
    if not os.path.isfile(path):
        return ''
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            return handle.read()
    except OSError:
        return ''


def has_spec(root):
    text = _read_spec(root)
    return 'location' in text.lower()


def _folder_sounds(folder):
    out = {}
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return out
    for leaf in names:
        stem, extension = os.path.splitext(leaf)
        if extension.lower() in _SOUND_SUFFIXES:
            out[stem] = os.path.join(folder, leaf)
    return out


def _pretty(name):
    stem = os.path.splitext(os.path.basename(name))[0]
    for prefix in ('t_', 'e_', 's_'):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    stem = stem.replace('_', ' ').replace('-', ' ').strip()
    return stem[:1].upper() + stem[1:] if stem else name
