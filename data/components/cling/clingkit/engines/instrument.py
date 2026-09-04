# -*- coding: utf-8 -*-
"""The keyboard as an instrument: a key, a sample, and the ones that loop.

Klango Piano and the Klango sound models (the Daft Punk set, the Mortal Kombat
voices) are the same application with different recordings, and the recordings
say everything: a folder of samples whose FILE NAME is the key that plays it.

    sounds/default_samples/z.wav      z plays it once
    sounds/default_samples/q_l.wav    q plays it as a loop, until q again
    sounds/default_samples/.info.txt  what the set is, in its author's words

There is no rule left to write down, which is why this engine exists: a sample
set somebody records tomorrow is a Cling application with no code at all, and
a set already on the user's disk plays without being converted.
"""

import os

from .base import Engine

_SOUND_SUFFIXES = ('.ogg', '.wav', '.mp3', '.flac')
#: A sample whose name ends in this is held down rather than struck.
LOOP_SUFFIX = '_l'
#: The folders a set of samples is looked for in, most specific first.
SET_FOLDERS = ('sounds', 'models', 'samples', 'skin')
#: What the key names in a file name are called when they cannot be typed.
_NAMED = {'comma': ',', 'dot': '.', 'period': '.', 'space': ' ',
          'semicolon': ';', 'slash': '/', 'minus': '-', 'equals': '=',
          'lbracket': '[', 'rbracket': ']', 'quote': "'", 'backslash': '\\'}


class InstrumentEngine(Engine):
    LABEL = 'instrument'

    def __init__(self, host):
        Engine.__init__(self, host)
        self.sets = []            # [(name, path)]
        self.set_index = 0
        self.samples = {}         # key -> (path, loops)
        self.playing = {}         # key -> handle
        self.info = ''

    # ------------------------------------------------------------- opening
    def start(self):
        self.running = True
        self.sets = _find_sets(self.host.app.path)
        if not self.sets:
            self.host.show(self.host.text(
                'no_samples', default='This application ships no sample set.'))
            self.finished_reason = 'no samples'
            return
        remembered = str(self.host.store.get('sample_set', '') or '')
        for index, (name, _path) in enumerate(self.sets):
            if name == remembered:
                self.set_index = index
                break
        welcome = self.host.text('welcome')
        self.host.show(welcome or self.host.app.name(self.host.language))
        self.load_set()

    def load_set(self):
        name, path = self.sets[self.set_index]
        self.stop_all_loops()
        self.samples = _read_set(path)
        self.info = _read_info(path)
        self.host.store.set('sample_set', name)
        self.host.show('%s (%d)' % (_pretty(name), len(self.samples)))

    # --------------------------------------------------------------- input
    def key(self, name, modifiers=()):
        name = (name or '').lower()
        if name == 'escape':
            self.stop()
            return True
        if name in ('pageup', 'pagedown') and len(self.sets) > 1:
            self.set_index = (self.set_index +
                              (1 if name == 'pagedown' else -1)) % len(self.sets)
            self.load_set()
            return True
        if name == 'f1':
            self.host.show(self.info or self.host.text('help'))
            return True
        if name == 'backspace':
            self.stop_all_loops()
            return True

        sample = self.samples.get(name)
        if sample is None:
            return False
        path, loops = sample
        if loops:
            # A loop is a switch, not a note: pressing its key again is how a
            # player stops the backing track they started.
            handle = self.playing.pop(name, None)
            if handle is not None:
                self.host.stop_sound(handle)
                return True
            started = self.host.mixer.loop(path, 0.0, 0.8)
            if started is not None:
                self.playing[name] = started
            return True
        self.host.mixer.play(path, 0.0, 0.0, 1.0)
        return True

    def stop_all_loops(self):
        for handle in list(self.playing.values()):
            self.host.stop_sound(handle)
        self.playing = {}

    def stop(self):
        self.stop_all_loops()
        Engine.stop(self)

    # ------------------------------------------------------------- reading
    def status(self):
        if not self.sets:
            return ''
        name = _pretty(self.sets[self.set_index][0])
        if self.playing:
            return '%s, %d looping' % (name, len(self.playing))
        return name

    def rows(self):
        return ['%s: %s%s' % (key, _pretty(os.path.splitext(
            os.path.basename(path))[0]), ' (loop)' if loops else '')
            for key, (path, loops) in sorted(self.samples.items())]

    def help_text(self):
        own = self.host.text('help')
        return own or self.info


def _find_sets(root):
    """Every folder of samples in the application, as (name, path)."""
    found = []
    for folder in SET_FOLDERS:
        base = os.path.join(root, folder)
        if not os.path.isdir(base):
            continue
        if _read_set(base):
            found.append((folder, base))
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            full = os.path.join(base, name)
            if os.path.isdir(full) and _read_set(full):
                found.append((name, full))
    return found


def _read_set(path):
    """key -> (file, loops). A name that is not one key is not a sample."""
    samples = {}
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return samples
    for leaf in names:
        stem, extension = os.path.splitext(leaf)
        if extension.lower() not in _SOUND_SUFFIXES:
            continue
        loops = stem.endswith(LOOP_SUFFIX)
        if loops:
            stem = stem[:-len(LOOP_SUFFIX)]
        key = _NAMED.get(stem.lower(), stem)
        if len(key) != 1:
            continue
        samples[key.lower()] = (os.path.join(path, leaf), loops)
    return samples


def _read_info(path):
    for leaf in ('.info.txt', 'info.txt', 'readme.txt'):
        candidate = os.path.join(path, leaf)
        if os.path.isfile(candidate):
            try:
                with open(candidate, 'r', encoding='utf-8',
                          errors='replace') as handle:
                    return handle.read().strip()
            except OSError:
                return ''
    return ''


def looks_like_instrument(root):
    return bool(_find_sets(root))


def _pretty(name):
    stem = str(name).replace('_', ' ').replace('-', ' ').strip()
    return stem[:1].upper() + stem[1:] if stem else str(name)
