# -*- coding: utf-8 -*-
"""Everything a Cling application says and plays, read the way Klango laid it out.

A Klango application keeps its words in `lang/<locale>/default/<name>.txt` -
one file per thing it can say, with `%d` where a number goes and a little bit
of markup (`<b>`, `<u>`) for the screens it shows.  Its sounds live in
`skin/<skin>/themes/<theme>/` and `skin/<skin>/events/`, its levels in
`skin/<skin>/levels/`.  Cling reads that layout unchanged, because the point of
the whole subsystem is that an application written for Klango is already a
Cling application: converting one would mean two copies of every text file and
a conversion step to forget to run.

The one addition is a fallback that Klango did not need and Cling does: a name
that no skin answers is looked for in Titan's own sound theme, so a Cling
application can be written that ships no audio at all and still sounds like the
rest of the desktop.
"""

import os
import re

from . import klango_lua

#: Where a locale name is written when the application only names a default.
DEFAULT_LOCALE_FILE = 'default'
#: The locale Klango applications fall back to when nothing else matches.
FALLBACK_LOCALE = 'en-us'

_TAG = re.compile(r'</?[a-zA-Z][^>]*>')
_SOUND_SUFFIXES = ('.ogg', '.wav', '.mp3', '.flac')


def strip_markup(text):
    """The text without Klango's display markup - what is spoken.

    `<b>Arrows</b> - move` is read out as the tags themselves by any screen
    reader handed it verbatim, and Titan's own speech would say "less than b
    greater than".  The markup is for the eye; the words are the application.
    """
    return _TAG.sub('', text or '').replace('&nbsp;', ' ')


def normalise_locale(code):
    """Titan says `pl`, Klango says `pl-pl`; this is the one place that knows."""
    code = (code or '').strip().lower().replace('_', '-')
    if not code:
        return ''
    if '-' in code:
        return code
    # `pl` -> `pl-pl`, `en` -> `en-us`: Klango's directories are always a pair,
    # and for every language but English the pair is the language twice.
    return 'en-us' if code == 'en' else '%s-%s' % (code, code)


class TextCatalogue(object):
    """The application's words, in the best locale it actually has.

    Resolution is Klango's own, in order: the locale asked for, the locale the
    application names in `lang/default`, `en-us`, then whatever single locale
    is there.  A name that no locale answers comes back as the empty string
    rather than raising - a missing `help.txt` must not stop a game.
    """

    def __init__(self, root, locale=''):
        self.root = root
        self.locale = ''
        self._order = []
        self._cache = {}
        self._resolve(locale)

    # ------------------------------------------------------------- locales
    def available_locales(self):
        lang_dir = os.path.join(self.root, 'lang')
        try:
            names = sorted(os.listdir(lang_dir))
        except OSError:
            return []
        return [name for name in names
                if os.path.isdir(os.path.join(lang_dir, name))]

    def _named_default(self):
        path = os.path.join(self.root, 'lang', DEFAULT_LOCALE_FILE)
        try:
            from . import textio
            return textio.read(path).strip().lower()
        except OSError:
            return ''

    def _resolve(self, locale):
        available = self.available_locales()
        wanted = []
        for candidate in (normalise_locale(locale), self._named_default(),
                          FALLBACK_LOCALE):
            if candidate and candidate not in wanted:
                wanted.append(candidate)
        order = [name for name in wanted if name in available]
        # A language whose region we guessed wrong ('pt-pt' asked, 'pt-br'
        # shipped) is still that language, and is a far better answer than
        # English.
        for candidate in wanted:
            prefix = candidate.split('-')[0]
            for name in available:
                if name.split('-')[0] == prefix and name not in order:
                    order.append(name)
        for name in available:
            if name not in order:
                order.append(name)
        self._order = order
        self.locale = order[0] if order else ''

    # --------------------------------------------------------------- texts
    def path_for(self, name):
        """Where `name` really is, across the locales, or ''."""
        leaf = name if name.endswith('.txt') else name + '.txt'
        for locale in self._order:
            candidate = os.path.join(self.root, 'lang', locale, 'default', leaf)
            if os.path.isfile(candidate):
                return candidate
            candidate = os.path.join(self.root, 'lang', locale, leaf)
            if os.path.isfile(candidate):
                return candidate
        return ''

    def raw(self, name, default=''):
        if name in self._cache:
            return self._cache[name]
        path = self.path_for(name)
        text = default
        if path:
            from . import textio
            found = textio.read_or_none(path)
            text = default if found is None else found
            if text[:1] == '﻿':
                text = text[1:]
            text = text.replace('\r\n', '\n').rstrip('\n')
        self._cache[name] = text
        return text

    def text(self, name, *values, **kwargs):
        """One of the application's texts, formatted and ready to be spoken.

        The `%d`/`%s` placeholders are the application's own, so the values are
        applied here; a text whose placeholders do not match what the engine
        passes comes back unformatted rather than raising, because a wrong
        count in somebody else's file is not a reason for the game to stop.
        """
        raw = self.raw(name, kwargs.get('default', ''))
        if values:
            try:
                raw = raw % values
            except (TypeError, ValueError):
                pass
        return strip_markup(raw) if kwargs.get('spoken', True) else raw

    def lines(self, name, *values):
        """The text as the lines it was written as, blank ones dropped."""
        text = self.text(name, *values)
        return [line.strip() for line in text.split('\n') if line.strip()]

    def has(self, name):
        return bool(self.path_for(name))

    def info(self):
        """`appinfo.txt` - `key:value` per line, the flags Klango reads."""
        out = {}
        for line in self.raw('appinfo').split('\n'):
            if ':' in line:
                key, _sep, value = line.partition(':')
                out[key.strip().lower()] = value.strip()
        return out


class Skin(object):
    """A skin directory: its sounds, its levels and the topologies they name."""

    def __init__(self, root, skin='default', theme='default'):
        self.root = root
        self.name = skin
        self.theme = theme
        self.path = os.path.join(root, 'skin', skin)
        if not os.path.isdir(self.path):
            self.path = self._first_skin() or self.path
            self.name = os.path.basename(self.path)
        self._all = None
        self.theme_path = os.path.join(self.path, 'themes', theme)
        if not os.path.isdir(self.theme_path):
            self.theme_path = self._first_theme() or self.theme_path
            self.theme = os.path.basename(self.theme_path)

    def _first_skin(self):
        base = os.path.join(self.root, 'skin')
        try:
            for name in sorted(os.listdir(base)):
                full = os.path.join(base, name)
                if os.path.isdir(full):
                    return full
        except OSError:
            pass
        return ''

    def _first_theme(self):
        base = os.path.join(self.path, 'themes')
        try:
            for name in sorted(os.listdir(base)):
                full = os.path.join(base, name)
                if os.path.isdir(full):
                    return full
        except OSError:
            pass
        return ''

    def themes(self):
        base = os.path.join(self.path, 'themes')
        try:
            return sorted(name for name in os.listdir(base)
                          if os.path.isdir(os.path.join(base, name)))
        except OSError:
            return []

    # -------------------------------------------------------------- sounds
    def sound(self, name):
        """Where a named sound really is: the theme, then the events, or ''.

        Klango names a theme sound `t_mole_hello` and an event `e_timeout`, and
        both are asked for without an extension - the file may be `.ogg` in one
        skin and `.wav` in another, and an application must not have to know.
        """
        if not name:
            return ''
        for folder in (self.theme_path, os.path.join(self.path, 'events'),
                       os.path.join(self.path, 'sound'),
                       os.path.join(self.path, 'sounds'),
                       os.path.join(self.path, 'settings'), self.path):
            found = _find_sound(folder, name)
            if found:
                return found
        # Skins do not agree about where sounds go - Mole keeps them in
        # `themes/` and `events/`, Skeet and Long Jump in `sound/`, Puzzle
        # loose in the skin - so the last resort is to look, once, everywhere
        # under the skin. The answer is remembered, because a game asks for
        # the same handful of names hundreds of times.
        return self._anywhere(name)

    def _anywhere(self, name):
        if self._all is None:
            self._all = {}
            for directory, _subdirs, files in os.walk(self.path):
                for leaf in sorted(files):
                    stem, extension = os.path.splitext(leaf)
                    if extension.lower() in _SOUND_SUFFIXES:
                        self._all.setdefault(stem.lower(),
                                             os.path.join(directory, leaf))
        return self._all.get(os.path.splitext(str(name))[0].lower(), '')

    def sounds(self):
        """Every sound the skin has, by the name an application would ask for."""
        out = {}
        for folder in (os.path.join(self.path, 'events'), self.theme_path,
                       os.path.join(self.path, 'sound'),
                       os.path.join(self.path, 'sounds')):
            try:
                names = sorted(os.listdir(folder))
            except OSError:
                continue
            for leaf in names:
                stem, extension = os.path.splitext(leaf)
                if extension.lower() in _SOUND_SUFFIXES:
                    out.setdefault(stem, os.path.join(folder, leaf))
        return out

    # -------------------------------------------------------------- levels
    @property
    def levels_path(self):
        return os.path.join(self.path, 'levels')

    def level_files(self):
        try:
            return [os.path.join(self.levels_path, name)
                    for name in sorted(os.listdir(self.levels_path))
                    if name.lower().endswith('.lev')]
        except OSError:
            return []

    def topology_file(self, name):
        candidate = os.path.join(self.levels_path, '%s.top' % name)
        return candidate if os.path.isfile(candidate) else ''

    def colours(self):
        """`settings/color.txt` - `key:r,g,b` or `key:number`."""
        path = os.path.join(self.path, 'settings', 'color.txt')
        out = {}
        from . import textio
        content = textio.read_or_none(path)
        if content is None:
            return out
        for line in content.split('\n'):
            if ':' not in line:
                continue
            key, _sep, value = line.partition(':')
            parts = [part.strip() for part in value.split(',') if part.strip()]
            try:
                numbers = [int(part) for part in parts]
            except ValueError:
                continue
            out[key.strip()] = tuple(numbers) if len(numbers) > 1 else numbers[0]
        return out


def _find_sound(folder, name):
    stem, extension = os.path.splitext(name)
    if extension.lower() in _SOUND_SUFFIXES:
        candidate = os.path.join(folder, name)
        return candidate if os.path.isfile(candidate) else ''
    for suffix in _SOUND_SUFFIXES:
        candidate = os.path.join(folder, stem + suffix)
        if os.path.isfile(candidate):
            return candidate
    return ''


def read_levels(skin, texts=None):
    """Every level the skin describes, in order, as plain dictionaries.

    A level file that cannot be read is skipped with its reason kept on the
    result, because thirteen levels of which one is broken is twelve levels
    and a message, not a game that refuses to start.
    """
    levels = []
    problems = []
    for path in skin.level_files():
        try:
            table = klango_lua.read_file(path, 'Level')
        except (klango_lua.LuaError, OSError) as error:
            problems.append('%s: %s' % (os.path.basename(path), error))
            continue
        if not isinstance(table, dict):
            problems.append('%s: not a level table' % os.path.basename(path))
            continue
        table = dict(table)
        table['file'] = path
        table.setdefault('name', os.path.splitext(os.path.basename(path))[0])
        levels.append(table)
    return levels, problems
