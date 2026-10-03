# -*- coding: utf-8 -*-
"""The settings ring: a few settings changed without leaving the work.

Insert+Ctrl+Left and Right choose a setting - the rate, the pitch, the
volume, the voice, the synthesizer, the speech scheme, the punctuation
level, the keyboard echo, the mouse - and Insert+Ctrl+Up and Down change
it, said as it changes. The entries are `settings_schema.RING`, so the
ring and the settings page cannot disagree about what a setting is
called or what it accepts; the change itself is `settings_walk.set_value`,
the same one Enter in the walked settings makes, so it is written and
applied the same way.
"""

import threading

from titan_access import settings_schema as schema
from titan_access import settings_walk as walk
from titan_access.localization import L

_LOCK = threading.RLock()


class SettingsRing(object):

    def __init__(self, engine):
        self.engine = engine
        self.at = 0
        self._counted = {'moved': 0, 'changed': 0}

    def report(self):
        found = dict(self._counted)
        found['at'] = self.at
        return found

    # ------------------------------------------------------------------ #
    def entries(self):
        """The ring's entries, in the walker's six-tuple shape."""
        found = []
        for section, key in schema.RING:
            entry = schema.find(section, key)
            if entry is not None:
                found.append((entry.section, entry.key, entry.label,
                              entry.kind, entry.extra, entry.default))
        return found

    def current(self):
        rows = self.entries()
        if not rows:
            return None
        with _LOCK:
            self.at = max(0, min(self.at, len(rows) - 1))
            return rows[self.at]

    def _label(self, entry):
        return L(entry[2]).strip().rstrip(':').strip()

    def say_current(self):
        entry = self.current()
        if entry is None:
            return False
        value = walk.value_of(entry)
        self.engine.speak('%s: %s' % (self._label(entry),
                                      walk.value_word(entry, value, self.engine)))
        return True

    def move(self, delta):
        rows = self.entries()
        if not rows:
            return False
        with _LOCK:
            self.at = (self.at + int(delta)) % len(rows)
            self._counted['moved'] += 1
        return self.say_current()

    def change(self, delta):
        """The next or previous value of the current entry, applied and said."""
        entry = self.current()
        if entry is None:
            return False
        kind = entry[3]
        now = walk.value_of(entry)
        if kind == 'bool':
            wanted = not bool(now)
        elif kind == 'range':
            low, high, step = entry[4]
            wanted = max(low, min(high, int(now) + int(delta) * int(step)))
            if wanted == now:
                self._edge()
                return True
        else:
            options = [value for value, _label in walk._options(entry, self.engine)]
            if not options:
                self.engine.speak(L('walk.nothingToChoose'))
                return True
            values = [str(one) for one in options]
            index = values.index(str(now)) if str(now) in values else -1
            index = index + int(delta)
            if index < 0 or index >= len(options):
                self._edge()
                return True
            wanted = options[index]
        walk.set_value(entry, wanted, self.engine)
        with _LOCK:
            self._counted['changed'] += 1
        self.engine.speak(walk.value_word(entry, walk.value_of(entry), self.engine))
        return True

    def _edge(self):
        try:
            self.engine.play('edge.ogg')
        except Exception:                            # noqa: BLE001
            pass
