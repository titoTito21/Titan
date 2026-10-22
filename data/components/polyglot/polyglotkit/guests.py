# -*- coding: utf-8 -*-
"""Running a program written in another language, and answering it.

Two shapes, one API:

* `LuaGuest` - Lua runs on a thread of this process, on the interpreter this
  component carries; ``titan`` is a table of native functions.
* `ProcessGuest` - anything else runs as a child process and speaks the line
  protocol on its standard streams:

      guest -> Titan   {"id": 1, "call": "speak", "args": {"text": "Hi"}}
      Titan -> guest   {"id": 1, "ok": true, "value": true}
                       {"id": 1, "ok": false, "error": "a sentence"}

  One JSON object per line, UTF-8. A call without an ``id`` is not answered.
  ``args`` may be an object (named) or an array (positional). A line that is
  not a JSON object is the program's own output and goes to the log - a stray
  ``print`` must never corrupt the conversation.

The protocol is synchronous on purpose: a guest writes a call and reads its
answer, so a client library in any language is a dozen lines with no threads.
Keys and other events are PULLED with ``next_event``.
"""

import json
import os
import subprocess
import sys
import threading
import traceback

from .api import ApiError
from .i18n import _


class Guest(object):
    def __init__(self, api, path, log, on_exit):
        self.api = api
        self.path = path
        self.log = log
        self.on_exit = on_exit          # (code, error_text) -> None
        self.thread = None

    def _finished(self, code, error=''):
        try:
            self.on_exit(code, error)
        except Exception:
            self.log(traceback.format_exc())


# ------------------------------------------------------------------------ Lua
class LuaGuest(Guest):
    """A Lua program on this component's own interpreter."""

    def __init__(self, api, path, log, on_exit, call_function=None):
        Guest.__init__(self, api, path, log, on_exit)
        from .lua import LuaRuntime
        self.runtime = LuaRuntime(os.path.dirname(os.path.abspath(path)),
                                  prefer_native=False)
        self.interpreter = self.runtime.interpreter
        # A game loop is long by design; the step ceiling is per "frame":
        # every wait or event read starts the count again, so only a loop
        # that never waits is stopped.
        api.tick = self._tick
        self.runtime.set_global('titan', self._titan_table())
        self.runtime.set_global('print', self._print)
        self.lock = threading.RLock()

    def _tick(self):
        self.interpreter.steps = 0

    def _print(self, *values):
        self.log(' '.join(self.interpreter.tostring(v) for v in values))

    # -- values between the two worlds
    def to_python(self, value, depth=0):
        from .lua import LuaTable
        if isinstance(value, LuaTable) and depth < 20:
            array = [value.raw_get(i) for i in range(1, value.length() + 1)]
            keys = [k for k in value.keys()
                    if not (isinstance(k, int) and 1 <= k <= len(array))]
            if not keys:
                return [self.to_python(v, depth + 1) for v in array]
            out = {str(k): self.to_python(value.raw_get(k), depth + 1)
                   for k in keys}
            for index, item in enumerate(array, start=1):
                out[str(index)] = self.to_python(item, depth + 1)
            return out
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    def to_lua(self, value):
        if isinstance(value, dict):
            return self.runtime.table({k: self.to_lua(v)
                                       for k, v in value.items()})
        if isinstance(value, (list, tuple)):
            return self.runtime.table({i: self.to_lua(v)
                                       for i, v in enumerate(value, start=1)})
        return value

    def _titan_table(self):
        api = self.api
        table = {}

        def native(name):
            def call(*arguments):
                try:
                    return answer(*arguments)
                except ApiError as error:
                    # A refusal is a Lua error, so `pcall` can catch it.
                    from .lua import LuaError
                    raise LuaError(str(error)) from None

            def answer(*arguments):
                args = [self.to_python(a) for a in arguments]
                if name == 'choose':
                    # Lua counts from 1, the protocol from 0.
                    if len(args) >= 4 and isinstance(args[3], int):
                        args[3] -= 1
                    result = api.dispatch(name, args)
                    return None if result is None else result + 1
                if name == 'action':
                    result = api.dispatch(name, args)
                    return result.get('ok'), result.get('text')
                return self.to_lua(api.dispatch(name, args))
            return call

        for name in api.CALLS:
            table[name] = native(name)
        table['sleep'] = table['wait']
        return self.runtime.table(table)

    def start(self):
        self.thread = threading.Thread(target=self._run, name='PolyglotLua',
                                       daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self.runtime.run_file(self.path)
            main = self.runtime.get_global('main')
            if main is not None and self.api.kind in ('app', 'game'):
                self.runtime.call(main)
        except Exception as error:
            self.log(traceback.format_exc())
            self._finished(1, str(error))
            return
        self._finished(self.api.exit_code or 0, '')

    def call_global(self, name, *arguments):
        """Call one of the program's own functions (a component's hooks)."""
        function = self.runtime.get_global(name)
        if function is None:
            return None
        with self.lock:
            return self.runtime.call(function,
                                     *[self.to_lua(a) for a in arguments])

    def stop(self):
        self.api.exit(0)
        self.api.post({'type': 'close'})


# -------------------------------------------------------------- other languages
class ProcessGuest(Guest):
    """A program in any language with a command line."""

    def __init__(self, api, path, log, on_exit, command, env=None, cwd=None):
        Guest.__init__(self, api, path, log, on_exit)
        self.command = command
        self.env = env
        self.cwd = cwd or os.path.dirname(os.path.abspath(path))
        self.process = None
        self.stderr_tail = []
        self._write_lock = threading.Lock()

    def start(self):
        kwargs = {}
        if sys.platform == 'win32':
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
        self.log('start: %s' % ' '.join(self.command))
        self.process = subprocess.Popen(
            self.command, cwd=self.cwd, env=self.env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        threading.Thread(target=self._read_errors, name='PolyglotStderr',
                         daemon=True).start()
        self.thread = threading.Thread(target=self._serve, name='PolyglotGuest',
                                       daemon=True)
        self.thread.start()

    def _read_errors(self):
        for raw in iter(self.process.stderr.readline, b''):
            line = raw.decode('utf-8', 'replace').rstrip()
            self.log('stderr: ' + line)
            self.stderr_tail.append(line)
            del self.stderr_tail[:-40]

    def _write(self, obj):
        data = (json.dumps(obj, ensure_ascii=False) + '\n').encode('utf-8')
        with self._write_lock:
            try:
                self.process.stdin.write(data)
                self.process.stdin.flush()
            except (OSError, ValueError):
                pass

    def handle_line(self, line):
        """One line from the guest. Answers what was written back, or None."""
        text = line.strip()
        if not text.startswith('{'):
            if text:
                self.log('output: ' + text)
            return None
        try:
            message = json.loads(text)
        except ValueError:
            self.log('output: ' + text)
            return None
        if not isinstance(message, dict) or 'call' not in message:
            self.log('output: ' + text)
            return None
        ident = message.get('id')
        try:
            value = self.api.dispatch(str(message.get('call')),
                                      message.get('args'))
            reply = {'id': ident, 'ok': True, 'value': value}
        except ApiError as error:
            reply = {'id': ident, 'ok': False, 'error': str(error)}
        except Exception as error:
            self.log(traceback.format_exc())
            reply = {'id': ident, 'ok': False,
                     'error': '%s: %s' % (type(error).__name__, error)}
        if ident is None:
            return None
        self._write(reply)
        return reply

    def _serve(self):
        for raw in iter(self.process.stdout.readline, b''):
            self.handle_line(raw.decode('utf-8', 'replace'))
        code = self.process.wait()
        self.api.exit_code = code if self.api.exit_code is None \
            else self.api.exit_code
        error = '\n'.join(self.stderr_tail[-15:]) if code else ''
        self._finished(code, error)

    def stop(self, grace=2.0):
        self.api.exit(0)
        self.api.post({'type': 'close'})
        if self.process is None:
            return
        try:
            self.process.wait(grace)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass


def make_guest(runtime, api, path, log, on_exit):
    """The right guest for this runtime. Raises RuntimeError with a sentence."""
    if runtime.inprocess:
        return LuaGuest(api, path, log, on_exit)
    if not runtime.available():
        raise RuntimeError(runtime.why_not())
    command = runtime.prepare(path, log=log)
    return ProcessGuest(api, path, log, on_exit, command,
                        env=runtime.environment(path))


def failure_text(name, code, error):
    return _("{} stopped with an error (code {}).\n\n{}").format(
        name, code, error or _("It said nothing about why."))
