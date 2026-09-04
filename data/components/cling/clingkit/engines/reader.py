# -*- coding: utf-8 -*-
"""Everything the application says, as a list somebody can actually read.

Not every application in `data/cling` is one Cling can play.  An application
whose logic was Lua in a package Cling has not got still ships all of its
words - its welcome, its instructions, its help, its thirteen level
descriptions - and a subsystem that answered such an application with nothing
would be hiding what is really there.

So the reader is the floor: it lists what the application says, in the user's
language, and says any of it aloud.  It is also the right engine in its own
right for the applications that are only text - a manual, a set of lessons, a
list of instructions - which is why it is not called `unsupported`.
"""

import os

from .base import Engine
from .. import resources

#: The texts every Klango application is likely to have, in the order a person
#: would want them.  Anything else it ships is listed after these.
KNOWN_ORDER = ('welcome', 'instructions', 'help', 'appinfo_summary',
               'current_status', 'highscores', 'new_game', 'quit_game')
#: Files that are Cling's own bookkeeping rather than something to read out.
SKIP = ('appinfo', 'klangomenu', 'lang')


class ReaderEngine(Engine):
    LABEL = 'text'

    def __init__(self, host):
        Engine.__init__(self, host)
        self.entries = []         # [(label, text)]
        self.index = 0

    def start(self):
        self.running = True
        self.entries = self._collect()
        if not self.entries:
            self.host.show(self.host.text(
                'empty', default='This application ships no text Cling can read.'))
            self.finished_reason = 'no text'
            return
        welcome = self.host.text('welcome')
        self.host.show(welcome or self.host.app.name(self.host.language))
        self.announce()

    def _collect(self):
        texts = self.host.texts
        locale = texts.locale
        folder = os.path.join(texts.root, 'lang', locale, 'default')
        if not os.path.isdir(folder):
            folder = os.path.join(texts.root, 'lang', locale)
        names = []
        try:
            for leaf in sorted(os.listdir(folder)):
                if leaf.lower().endswith('.txt'):
                    names.append(os.path.splitext(leaf)[0])
        except OSError:
            names = []
        ordered = [name for name in KNOWN_ORDER if name in names]
        ordered += [name for name in names
                    if name not in ordered and name not in SKIP]
        entries = []
        for name in ordered:
            body = texts.text(name)
            if body:
                entries.append((_pretty(name), body))
        return entries

    def announce(self):
        label, _body = self.entries[self.index]
        self.host.say('%s, %d/%d' % (label, self.index + 1, len(self.entries)))

    def key(self, name, modifiers=()):
        name = (name or '').lower()
        if not self.entries:
            return False
        if name in ('up', 'left'):
            self.index = (self.index - 1) % len(self.entries)
            self.announce()
            return True
        if name in ('down', 'right'):
            self.index = (self.index + 1) % len(self.entries)
            self.announce()
            return True
        if name in ('enter', 'space'):
            self.host.show(self.entries[self.index][1])
            return True
        if name == 'escape':
            self.stop()
            return True
        return False

    def status(self):
        if not self.entries:
            return ''
        return '%s (%d/%d)' % (self.entries[self.index][0],
                               self.index + 1, len(self.entries))

    def rows(self):
        return [label for label, _body in self.entries]

    def read(self, index):
        """The whole of one entry - what the browser shows when Enter is hit."""
        if 0 <= index < len(self.entries):
            return resources.strip_markup(self.entries[index][1])
        return ''


def _pretty(name):
    stem = str(name).replace('_', ' ').replace('-', ' ').strip()
    return stem[:1].upper() + stem[1:] if stem else str(name)
