# -*- coding: utf-8 -*-
"""An application that brings its own logic, in Lua or in Python.

This is the general answer, and the one that makes "every Cling application
runs" true rather than aspirational: the data-driven engines beside it cover
the genres whose rules are entirely in the data, and everything else ships
`main.lua` and is a program.

The Lua goes through the interpreter this component carries, so an application
written in Lua - which is what applications of this kind have always been
written in - runs on a machine with no Lua installed anywhere.  The contract is
five functions, all optional:

    function on_start()          the application has been opened
    function on_key(key)         'up' 'down' 'left' 'right' 'space' 'enter'
                                 'escape' 'a'..'z' '0'..'9' 'f1'..; true when
                                 the key was used
    function on_tick(now)        called often; `now` is seconds, monotonic
    function on_stop()           the application is being left
    function status()            one line for the status bar

and one global, `cling`, which is the host: everything the application can say,
play, remember and ask.  Nothing else is in scope - no file system, no network,
no way to start a program - because the application came from wherever the user
found it.
"""

import os
import traceback

from .base import Engine
from .. import topology as topology_module


class ScriptEngine(Engine):
    LABEL = 'application'

    def __init__(self, host):
        Engine.__init__(self, host)
        self.path = host.app.entry_path()
        self.kind = 'lua' if self.path.lower().endswith('.lua') else 'python'
        self.runtime = None
        self.namespace = {}
        self.error = ''
        self._handles = {}
        self._next_handle = 1
        self._boards = {}
        self._board = None        # the one the application last asked for
        self._status = ''

    # ------------------------------------------------------------ lifetime
    def start(self):
        self.running = True
        if not self.path:
            self.error = 'this application names no main.lua or main.py'
            self.host.show(self.error)
            self.finished_reason = 'no entry point'
            return
        try:
            if self.kind == 'lua':
                self._start_lua()
            else:
                self._start_python()
        except Exception as error:
            self._blame(error)
            return
        self._invoke('on_start')

    def _start_lua(self):
        from ..lua import LuaRuntime
        self.runtime = LuaRuntime(self.host.app.path)
        self.runtime.set_global('cling', self._api_table())
        self.runtime.run_file(self.path)

    def _start_python(self):
        with open(self.path, 'r', encoding='utf-8', errors='replace') as handle:
            source = handle.read()
        self.namespace = {'__name__': 'cling_app', '__file__': self.path,
                          'cling': _PythonApi(self)}
        exec(compile(source, self.path, 'exec'), self.namespace)

    def stop(self):
        if self.running:
            self._invoke('on_stop')
        for handle in list(self._handles.values()):
            self.host.stop_sound(handle)
        self._handles = {}
        Engine.stop(self)

    # -------------------------------------------------------------- events
    def tick(self, now=None):
        if not self.running or self.error:
            return
        self._invoke('on_tick', self.host.now() if now is None else now)

    def key(self, name, modifiers=()):
        if self.error:
            if (name or '').lower() == 'escape':
                self.stop()
                return True
            return False
        result = self._invoke('on_key', (name or '').lower())
        if _truthy(result):
            return True
        if (name or '').lower() == 'escape':
            self.stop()
            return True
        return False

    def status(self):
        result = self._invoke('status')
        if isinstance(result, str) and result:
            return result
        return self._status

    def help_text(self):
        result = self._invoke('help')
        if isinstance(result, str) and result:
            return result
        return Engine.help_text(self)

    # ------------------------------------------------------------- calling
    def _invoke(self, name, *arguments):
        """Call one of the application's functions, whichever language it is in.

        An application that raises is stopped and the reason is SAID, not
        printed: the user of this subsystem cannot see a console, and a game
        that goes quiet with no explanation is indistinguishable from one that
        has crashed the whole desktop.
        """
        try:
            if self.kind == 'lua':
                if self.runtime is None or not self.runtime.has_global(name):
                    return None
                return self.runtime.call_global(name, *arguments)
            function = self.namespace.get(name)
            if not callable(function):
                return None
            return function(*arguments)
        except Exception as error:
            self._blame(error)
            return None

    def _blame(self, error):
        self.error = '%s: %s' % (os.path.basename(self.path or 'application'),
                                 error)
        self.finished_reason = 'error'
        print('[cling] %s' % self.error)
        traceback.print_exc()
        try:
            self.host.show(self.error)
        except Exception:
            pass
        self.running = False

    # ----------------------------------------------------------- the host
    def _api_table(self):
        """The `cling` table a Lua application sees."""
        api = _PythonApi(self)
        table = self.runtime.table({})
        for name in _API_NAMES:
            table.raw_set(name, getattr(api, name)) if hasattr(table, 'raw_set') \
                else table.__setitem__(name, getattr(api, name))
        return table

    # ------------------------------------------------------------- boards
    def board_for(self, name, columns=0, rows=0):
        """The board the application asked for, built once and remembered.

        Asking for one also makes it the CURRENT board, which is what
        `cling.field(n)` means when it is called with no board named - an
        application that laid out a three by three board and then asks for
        field 7 means that board, and answering out of a differently shaped
        one is the kind of bug that looks like the game having no sense of
        where anything is.
        """
        key = (str(name), int(columns or 0), int(rows or 0))
        if key not in self._boards:
            if columns and rows and not name:
                board = topology_module.Board.grid(int(columns), int(rows))
            else:
                board = topology_module.load(self.host.skin, name,
                                             int(columns or 0), int(rows or 0))
            self._boards[key] = board
        self._board = self._boards[key]
        return self._board

    def current_board(self):
        """The board in play, or an even one when nothing has asked yet."""
        if self._board is None:
            self._board = topology_module.Board.grid(3, 3)
        return self._board


_API_NAMES = ('say', 'say_at', 'text', 'show', 'play', 'play_at', 'loop',
              'stop_sound', 'stop_sounds', 'board', 'field', 'fields',
              'get', 'set', 'record_score', 'scores', 'best', 'now',
              'set_status', 'close', 'language', 'app_name', 'log',
              'account', 'sign_in', 'signed_in', 'publish_score',
              'leaderboard', 'fetch', 'ask')


class _PythonApi(object):
    """One object with everything an application may do, in both languages.

    Written once and handed to both backends on purpose: a Lua application and
    a Python one that do the same thing must behave identically, and the way
    to guarantee that is for there to be one implementation rather than two.
    """

    def __init__(self, engine):
        self._engine = engine
        self._host = engine.host

    # ------------------------------------------------------------- speech
    def say(self, text=None, position=0.0, pitch=0.0):
        return self._host.say(_text(text), _number(position), _number(pitch))

    def say_at(self, text=None, index=None):
        return self._host.say_at(_text(text), self._field(index))

    def text(self, name=None, *values):
        return self._host.text(_text(name), *values)

    def show(self, text=None):
        self._host.show(_text(text))

    # -------------------------------------------------------------- sound
    def play(self, name=None, position=0.0, gain=1.0):
        return self._host.play(_text(name), _number(position), 0.0,
                               _number(gain, 1.0))

    def play_at(self, name=None, index=None, gain=1.0):
        return self._host.play_at(_text(name), self._field(index),
                                  _number(gain, 1.0))

    def loop(self, name=None, position=0.0, gain=0.6):
        handle = self._host.loop(_text(name), _number(position),
                                 _number(gain, 0.6))
        if handle is None:
            return 0
        number = self._engine._next_handle
        self._engine._next_handle += 1
        self._engine._handles[number] = handle
        return number

    def stop_sound(self, handle=None):
        number = int(_number(handle))
        found = self._engine._handles.pop(number, None)
        if found is not None:
            self._host.stop_sound(found)

    def stop_sounds(self):
        self._host.stop_sounds()
        self._engine._handles = {}

    # -------------------------------------------------------------- board
    def board(self, name=None, columns=0, rows=0):
        board = self._engine.board_for(_text(name), _number(columns),
                                       _number(rows))
        return len(board)

    def fields(self, name=None, columns=0, rows=0):
        return len(self._engine.board_for(_text(name), _number(columns),
                                          _number(rows)))

    def field(self, index=None, name=None):
        board = self._engine.board_for(_text(name)) if name \
            else self._engine.current_board()
        found = board.by_index(int(_number(index, 1)))
        if found is None:
            return None
        return self._describe(found)

    def _describe(self, found):
        values = {'index': found.index, 'column': found.column,
                  'row': found.row, 'layer': found.layer,
                  'pan': found.pan, 'elevation': found.elevation,
                  'gain': found.gain, 'pitch': found.semitones}
        if self._engine.kind == 'lua' and self._engine.runtime is not None:
            return self._engine.runtime.table(values)
        return values

    def _field(self, index):
        if index is None:
            return None
        return self._engine.current_board().by_index(int(_number(index, 1)))

    # ------------------------------------------------------------ storage
    def get(self, key=None, default=None):
        return self._host.store.get(_text(key), default)

    def set(self, key=None, value=None):
        return self._host.store.set(_text(key), value)

    def record_score(self, points=0, name=''):
        return self._host.store.record_score(int(_number(points)), _text(name))

    def scores(self):
        return [int(entry.get('points', 0))
                for entry in self._host.store.scores()]

    def best(self):
        return self._host.store.best()

    # ------------------------------------------------------------ account
    def account(self):
        """The player's name. Klango asked for its own account; this is the
        Titan-Net one the user already has."""
        return self._host.whoami().name

    def signed_in(self):
        return bool(self._host.whoami().online)

    def sign_in(self):
        """Sign in headlessly with what the user saved. Returns the name, or ''.

        The reason a refusal comes back as an empty name rather than as an
        exception is that most applications should carry on without an
        account - a game with online scores is still a game.
        """
        account, error = self._host.sign_in()
        if error and not account.online:
            self._host.show(error)
            return ''
        return account.name

    def publish_score(self, points=0, level=0):
        published, message = self._host.publish_score(
            int(_number(points)), {'level': int(_number(level))} if level else None)
        if not published and message:
            self._engine._status = message
        return bool(published)

    def leaderboard(self, limit=10):
        rows = self._host.leaderboard(int(_number(limit, 10)))
        lines = ['%d. %s: %d' % (position, row.get('name') or '?',
                                 int(row.get('points', 0) or 0))
                 for position, row in enumerate(rows, start=1)]
        if self._engine.kind == 'lua' and self._engine.runtime is not None:
            table = self._engine.runtime.table({})
            for index, line in enumerate(lines, start=1):
                table.raw_set(index, line) if hasattr(table, 'raw_set') \
                    else table.__setitem__(index, line)
            return table
        return lines

    # ---------------------------------------------------------- the world
    def fetch(self, url=None, timeout=8.0):
        """Fetch a page. Answers the text, or '' with the reason on the status."""
        body, problem = self._host.http_get(_text(url), _number(timeout, 8.0))
        if problem:
            self._engine._status = problem
            return ''
        return body

    def ask(self, prompt=None, default=None):
        return self._host.ask(_text(prompt), _text(default))

    # --------------------------------------------------------------- misc
    def now(self):
        return self._host.now()

    def set_status(self, text=None):
        self._engine._status = _text(text)

    def close(self):
        self._engine.stop()

    def language(self):
        return self._host.texts.locale

    def app_name(self):
        return self._host.app.name(self._host.language)

    def log(self, text=None):
        print('[cling:%s] %s' % (self._host.app.id, _text(text)))


def _text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return value if isinstance(value, str) else str(value)


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _truthy(value):
    return not (value is None or value is False or value == 0)
