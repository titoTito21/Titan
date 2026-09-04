# -*- coding: utf-8 -*-
"""The board games: something appears somewhere, and you have to get to it.

This is the engine Mole No More runs on, and it is written from that game's own
data rather than from a memory of playing it.  Every rule below is a key in the
level file:

    Level = {
      text = "level5_info",   what the level says before it starts
      topology = "3x3",       which board, and therefore where every field IS
      fields = 9,             how many fields that board has
      hit_target = 30,        how many must be hit to finish the level
      nmole_time = 3,         how long an ordinary one stays up (0 = for ever)
      smole_time = 2.5,       how long a special one stays up
      max_nmoles = 2,         how many ordinary ones may be up at once
      max_smoles = 1,         how many special ones
      smole_time_bonus = 2,   seconds a special one adds to the clock
    }

Nothing about moles is in the engine's vocabulary: an "occupant" appears on a
field, is ordinary or special, and is hit or missed.  The sounds and the words
are the application's - `t_mole_hello`, `t_smole_bye`, `instructions.txt` - so
the same engine runs a game about birds, or bells, or doors, without a line
changing.
"""

import random

from .base import Engine
from .. import resources, topology as topology_module

#: What one hit is worth.  A game that wants its own says so in the level.
NORMAL_POINTS = 1
SPECIAL_POINTS = 5
#: How long a level lasts when neither the level nor the manifest says.
DEFAULT_SECONDS = 60
#: How long the engine waits between one occupant leaving and the next arriving.
SPAWN_GAP = 0.35


class Occupant(object):
    """Something on a field, waiting to be hit."""

    __slots__ = ('field', 'special', 'appeared', 'until')

    def __init__(self, field, special, appeared, lifetime):
        self.field = field
        self.special = special
        self.appeared = appeared
        self.until = 0.0 if lifetime <= 0 else appeared + lifetime

    def expired(self, now):
        return bool(self.until) and now >= self.until


class GridHuntEngine(Engine):
    """A board, a cursor, a clock, and things that come and go on the board."""

    LABEL = 'game'

    def __init__(self, host, seed=None):
        Engine.__init__(self, host)
        self.random = random.Random(seed)
        self.levels, self.level_problems = resources.read_levels(host.skin)
        self.level_index = 0
        self.board = None
        self.cursor = None
        self.occupants = []
        self.started_at = 0.0
        self.deadline = 0.0
        self.paused_at = 0.0
        self.next_spawn = 0.0
        self.points = 0
        self.normal_hits = 0
        self.special_hits = 0
        self.misses = 0
        self.state = 'idle'       # idle / briefing / playing / over / complete
        self._background = None
        self._session_points = 0
        self._session_normal = 0
        self._session_special = 0
        self._session_misses = 0

    # ------------------------------------------------------------- the game
    def start(self):
        self.running = True
        for problem in self.level_problems:
            self.host.show(problem)
        if not self.levels:
            # A board game with no levels is not a board game; the engine says
            # so instead of putting up an empty board the player cannot leave.
            self.state = 'over'
            self.finished_reason = 'no levels'
            self.host.show(self.host.text(
                'no_levels', default='This application has no levels Cling can read.'))
            return
        welcome = self.host.text('welcome')
        if welcome:
            self.host.show(welcome)
        self.level_index = int(self.host.store.get('level', 0) or 0)
        if self.level_index >= len(self.levels):
            self.level_index = 0
        self.brief()

    def brief(self):
        """Say what this level is before it starts. Space begins it."""
        self.state = 'briefing'
        level = self.levels[self.level_index]
        self.host.show(self.host.text('level_name', default='') or
                       _level_title(self.host, self.level_index, len(self.levels)))
        info = self.host.text(str(level.get('text') or ''))
        if info:
            self.host.show(info)
        instructions = self.host.text('instructions', self.seconds_for(level))
        if instructions and self.level_index == 0:
            self.host.show(instructions)
        self.host.show(self.host.text(
            'press_space', default='Press space to begin.'))

    def seconds_for(self, level):
        for key in ('time', 'game_time', 'seconds'):
            if level.get(key):
                try:
                    return int(float(level[key]))
                except (TypeError, ValueError):
                    pass
        declared = self.host.app.manifest.get('game_time') \
            or self.host.app.kni.get('game_time') or ''
        try:
            return int(float(declared))
        except (TypeError, ValueError):
            return DEFAULT_SECONDS

    def begin_level(self):
        level = self.levels[self.level_index]
        name = level.get('topology')
        self.board = topology_module.load(
            self.host.skin, name,
            int(level.get('fields', 0) or 0), 0)
        self.cursor = self.board.by_index(1)
        self.occupants = []
        self.points = 0
        self.normal_hits = 0
        self.special_hits = 0
        self.misses = 0
        now = self.host.now()
        self.started_at = now
        self.deadline = now + self.seconds_for(level)
        self.next_spawn = now
        self.state = 'playing'
        self._background = self.host.loop('t_background', gain=0.4)
        self.announce_cursor(move_sound=False)

    # ------------------------------------------------------------- the loop
    def tick(self, now=None):
        if self.state != 'playing':
            return
        now = self.host.now() if now is None else now

        for occupant in list(self.occupants):
            if occupant.expired(now):
                self.occupants.remove(occupant)
                self.host.play_at('t_smole_bye' if occupant.special
                                  else 't_mole_bye', occupant.field)
                self.next_spawn = max(self.next_spawn, now + SPAWN_GAP)

        if now >= self.next_spawn:
            if self.spawn(now):
                self.next_spawn = now + SPAWN_GAP

        if now >= self.deadline:
            self.time_up()

    def spawn(self, now):
        level = self.levels[self.level_index]
        normal = sum(1 for one in self.occupants if not one.special)
        special = sum(1 for one in self.occupants if one.special)
        max_normal = int(level.get('max_nmoles', 1) or 0)
        max_special = int(level.get('max_smoles', 0) or 0)

        wants_special = special < max_special and (
            normal >= max_normal or self.random.random() < 0.25)
        if not wants_special and normal >= max_normal:
            return False
        if wants_special and special >= max_special:
            return False

        taken = {one.field.index for one in self.occupants}
        free = [field for field in self.board if field.index not in taken]
        if not free:
            return False
        field = self.random.choice(free)
        lifetime = float(level.get('smole_time' if wants_special
                                   else 'nmole_time', 0) or 0)
        occupant = Occupant(field, wants_special, now, lifetime)
        self.occupants.append(occupant)
        self.host.play_at('t_smole_hello' if wants_special else 't_mole_hello',
                          field)
        return True

    # ---------------------------------------------------------------- input
    def key(self, name, modifiers=()):
        name = (name or '').lower()
        if self.state == 'briefing':
            if name in ('space', 'enter'):
                self.begin_level()
                return True
            if name == 'escape':
                self.stop()
                return True
            return False

        if self.state in ('over', 'complete'):
            if name in ('space', 'enter'):
                self.restart()
                return True
            return False

        if self.state != 'playing':
            return False

        if name in ('left', 'right', 'up', 'down'):
            self.move(name)
            return True
        if name == 'space':
            self.strike()
            return True
        if name in ('enter', 'f1'):
            self.host.show(self.status())
            return True
        if name == 'escape':
            self.time_up(quit_game=True)
            return True
        return False

    def move(self, direction):
        step = {'left': (-1, 0), 'right': (1, 0),
                'up': (0, -1), 'down': (0, 1)}[direction]
        target = self.board.step(self.cursor, columns=step[0], rows=step[1])
        if target is None:
            self.host.play('t_border')
            return
        self.cursor = target
        self.announce_cursor()

    def announce_cursor(self, move_sound=True):
        if move_sound:
            self.host.play_at('t_move', self.cursor)
        if self.occupant_here() is not None:
            self.host.play_at('t_walk_on_mole', self.cursor)

    def occupant_here(self):
        for occupant in self.occupants:
            if occupant.field.index == self.cursor.index:
                return occupant
        return None

    def strike(self):
        occupant = self.occupant_here()
        if occupant is None:
            self.misses += 1
            self.host.play_at('t_miss', self.cursor)
            return
        self.occupants.remove(occupant)
        self.host.play_at('t_mole_auu', occupant.field)
        level = self.levels[self.level_index]
        if occupant.special:
            self.special_hits += 1
            self.points += SPECIAL_POINTS
            self.host.play('e_earn_points2')
            bonus = float(level.get('smole_time_bonus', 0) or 0)
            if bonus:
                self.deadline += bonus
        else:
            self.normal_hits += 1
            self.points += NORMAL_POINTS
            self.host.play('e_earn_points1')
        self.next_spawn = min(self.next_spawn, self.host.now() + SPAWN_GAP)
        if self.hits >= int(level.get('hit_target', 0) or 0) > 0:
            self.level_finished()

    # --------------------------------------------------------------- counts
    @property
    def hits(self):
        return self.normal_hits + self.special_hits

    def time_left(self):
        if self.state != 'playing':
            return 0
        return max(0, int(round(self.deadline - self.host.now())))

    def status(self):
        if self.state == 'playing':
            text = self.host.text('current_status', self.points,
                                  self.normal_hits, self.special_hits,
                                  self.time_left())
            if text:
                return ' '.join(line for line in text.split('\n') if line)
        return self.host.text('appinfo_status', default='') or ''

    # ------------------------------------------------------------- endings
    def _fold_session(self):
        self._session_points += self.points
        self._session_normal += self.normal_hits
        self._session_special += self.special_hits
        self._session_misses += self.misses

    def level_finished(self):
        self._quieten()
        self._fold_session()
        self.host.show(self.host.text('level_finished_dialog_head',
                                      default='Level scores'))
        self.host.show(self.host.text('game_finished_dialog', self.hits,
                                      self.normal_hits, self.special_hits,
                                      self.points))
        self.level_index += 1
        self.host.store.set('level', self.level_index)
        if self.level_index >= len(self.levels):
            self.game_complete()
            return
        self.brief()

    def game_complete(self):
        self.state = 'complete'
        self.finished_reason = 'complete'
        self.host.show(self.host.text('game_complete_head',
                                      default='Game completed'))
        self.host.show(self.host.text('game_complete',
                                      default='You have completed the game.'))
        self.record()
        self.host.store.set('level', 0)

    def time_up(self, quit_game=False):
        self._quieten()
        self._fold_session()
        self.state = 'over'
        self.finished_reason = 'quit' if quit_game else 'time'
        if not quit_game:
            self.host.play('e_timeout')
            self.host.show(self.host.text('timeup_head', default='Game Over'))
            self.host.show(self.host.text('timeup',
                                          default='The time is up.'))
        self.host.show(self.host.text('game_finished_dialog_head',
                                      default='Game scores'))
        self.host.show(self.host.text('game_finished_dialog', self.hits,
                                      self.normal_hits, self.special_hits,
                                      self.points))
        self.record()

    def record(self):
        # The score is written locally FIRST and unconditionally: the shared
        # table is a nicety, and a game that lost a score because a server was
        # not there would have got the order wrong.
        place = self.host.store.record_score(
            self._session_points, name=self.host.whoami().name,
            table='default',
            extra={'level': self.level_index + 1,
                   'moles': self._session_normal + self._session_special,
                   'normal': self._session_normal,
                   'special': self._session_special,
                   'fails': self._session_misses})
        if place == 1 and self._session_points:
            self.host.show(self.host.text('highscores', default='Highscores'))
        if self._session_points:
            # Klango games of this kind had online high scores behind a Klango
            # account; the account here is the user's Titan-Net one, and a
            # player who has never signed in simply keeps their own table.
            published, _message = self.host.publish_score(
                self._session_points, {'level': self.level_index + 1})
            if published:
                self.host.show(self.host.text(
                    'scores_published',
                    default='Your score was sent to the Titan-Net table.'))

    def restart(self):
        self._session_points = 0
        self._session_normal = 0
        self._session_special = 0
        self._session_misses = 0
        self.brief()

    def _quieten(self):
        if self._background is not None:
            self.host.stop_sound(self._background)
            self._background = None

    def stop(self):
        self._quieten()
        Engine.stop(self)

    # ---------------------------------------------------------------- lists
    def rows(self):
        """The high scores, said the way the application says them."""
        rows = []
        template = self.host.texts.raw('scores_info')
        for position, entry in enumerate(self.host.store.scores(), start=1):
            if template:
                try:
                    rows.append(resources.strip_markup(template % (
                        position, entry.get('name') or '-',
                        int(entry.get('points', 0)), int(entry.get('level', 0)),
                        int(entry.get('moles', 0)), int(entry.get('normal', 0)),
                        int(entry.get('special', 0)), int(entry.get('fails', 0)))))
                    continue
                except (TypeError, ValueError):
                    pass
            rows.append('%d. %d' % (position, int(entry.get('points', 0))))
        return rows


def _level_title(host, index, total):
    return host.text('level_of', index + 1, total,
                     default='Level %d of %d') % (index + 1, total) \
        if host.texts.has('level_of') else 'Level %d of %d' % (index + 1, total)
