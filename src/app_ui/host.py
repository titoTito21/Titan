# -*- coding: utf-8 -*-
"""Titan's side: launch a TCE application whose interface is somewhere else.

The reverse of `data/components/elten_bridge/eltenkit/bridge.py`, and
deliberately its twin - that one runs somebody else's application inside
Titan's interface, this one runs Titan's application inside somebody
else's. Both are one JSON object per line over a subprocess's own pipes,
and both take stdout away from the application first.

**A subprocess, not this process.** `app_manager` already launches every
TCE application that way and the reason holds here too: an application
that loops for ever, exhausts its stack or segfaults a library takes down
a subprocess, not Titan - and closing the window kills it, which is a
guarantee no in-process shim can make.
"""

import json
import os
import subprocess
import sys
import threading

from src.app_ui import wire

#: Where the shim lives. Put FIRST on the application's path, so its own
#: `import wx` reaches it before the real wxPython.
SHIM = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shim')

#: Long enough for an application that reads a folder on a slow disk before
#: it puts anything up, short enough that a dead one is noticed.
START_WAIT = 20.0

MAX_LOG = 400

#: A refusal that IS the interface. An application built on one of these
#: has nothing left to describe, and there is no point waiting for it.
#: `wx.Timer` is deliberately not here: plenty of applications ask for a
#: timer and describe themselves perfectly well without one.
#: `wx.html2` is not here: a page IS describable - as the text somebody
#: would read out of it - so a browser is an application like any other
#: now, and only a media surface and a drawing canvas are not.
FATAL = ('wx.media', 'wx.glcanvas')


class Application(object):
    """One TCE application, running with its interface described rather
    than drawn."""

    def __init__(self, entry, name=''):
        self.entry = entry              # the .py to run
        self.name = name or os.path.basename(os.path.dirname(entry))
        self.process = None
        self.screen = None
        self.status = ''
        self.detail = ''
        self.log = []
        self.refused = []
        #: Every wx name it asked for that the shim has not got. Read it
        #: to find out what an application still needs, rather than
        #: reading its source and guessing.
        self.unknown = []
        self.ready = False
        self.started = threading.Event()
        self.ended = threading.Event()
        self.changed = threading.Event()
        self._writing = threading.Lock()

    # ------------------------------------------------------------- start
    def start(self, python=None):
        folder = os.path.dirname(os.path.abspath(self.entry))
        environment = dict(os.environ)
        # The shim first, then the application's own folder, then Titan -
        # the same order `app_manager` builds, with one entry in front.
        paths = [SHIM, folder, _titan_root()]
        existing = environment.get('PYTHONPATH', '')
        if existing:
            paths.append(existing)
        environment['PYTHONPATH'] = os.pathsep.join(paths)
        environment['TITAN_APP_UI'] = '1'
        environment['PYTHONIOENCODING'] = 'utf-8'
        environment.pop('PYTHONHOME', None)

        command = [python or _python(), '-X', 'utf8', '-c', _BOOT % {
            'shim': SHIM.replace('\\', '\\\\'),
            'folder': folder.replace('\\', '\\\\'),
            'titan': _titan_root().replace('\\', '\\\\'),
            'entry': os.path.abspath(self.entry).replace('\\', '\\\\')}]

        creation = 0
        startup = None
        if os.name == 'nt':
            creation = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            self.process = subprocess.Popen(
                command, cwd=folder, env=environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, creationflags=creation,
                startupinfo=startup)
        except Exception as error:
            self.status, self.detail = 'failed', str(error)
            self.ended.set()
            return False
        threading.Thread(target=self._read, name='app-ui', daemon=True).start()
        threading.Thread(target=self._read_log, name='app-ui-log',
                         daemon=True).start()
        if not self.started.wait(START_WAIT) or self.screen is None:
            self.status = 'failed'
            # **Say which part of it cannot be here.** An application whose
            # interface IS a web view or a media surface has nothing to
            # describe, and "it did not describe an interface" is true and
            # useless. The shim already recorded what it refused, and that
            # is the real answer.
            self.detail = (self.detail or self._what_it_needed()
                           or _last_words(self.log)
                           or 'the application did not describe an interface')
            self.stop()
            return False
        self.status = 'running'
        return True

    def _what_it_needed(self):
        """The refusal that explains an application showing nothing.

        `wx.Timer` is not one: plenty of applications ask for a timer and
        show their interface perfectly well without it. A web view or a
        media surface IS the interface, and an application built on one
        has nothing left to describe.
        """
        fatal = [entry for entry in self.refused
                 if entry.get('what') in FATAL]
        if not fatal:
            return ''
        return '%s is built on %s: %s' % (
            self.name, fatal[0]['what'], fatal[0]['detail'])

    # -------------------------------------------------------------- wire
    def _read(self):
        try:
            for raw in wire.lines(self.process.stdout):
                message = wire.unpack(raw)
                if message is None:
                    continue
                self._heard(message)
        except Exception as error:
            self._note('bridge', 'the wire failed: %s' % error)
        finally:
            self.ended.set()
            self.started.set()
            self.changed.set()

    def _heard(self, message):
        what = str(message.get('do') or '')
        if what == 'screen':
            self.screen = message.get('screen')
            self.started.set()
            self.changed.set()
        elif what == 'ready':
            # **Not `started`.** "the shim is up" and "there is something
            # to show" are different moments and the second is the one a
            # caller is waiting for: released on the first, `start()`
            # returned with `screen` still None and the interface arrived
            # a heartbeat later, which every caller then read as an
            # application that showed nothing.
            self.refused = list(message.get('refused') or [])
            self.ready = True
        elif what == 'refused':
            self.refused.append({'what': message.get('what', ''),
                                 'detail': message.get('detail', '')})
            self._note('refused', '%s: %s' % (message.get('what', ''),
                                              message.get('detail', '')))
            # **Give up now, not in twenty seconds.** A refusal that IS
            # the interface - a web view, a media surface - arrives at the
            # application's first line, and waiting out the full start-up
            # window for a screen that cannot come made opening the
            # browser take 28 seconds when the floor underneath needs one.
            if message.get('what') in FATAL:
                self.started.set()
        elif what == 'report':
            self.unknown = list(message.get('unknown') or [])
            self.refused = list(message.get('refused') or self.refused)
            self.changed.set()
        elif what == 'said':
            self._note('app', str(message.get('text') or ''))
        elif what == 'gone':
            self.status = 'finished'
            self.started.set()
            self.ended.set()

    def _read_log(self):
        try:
            for raw in wire.lines(self.process.stderr):
                self._note('stderr', raw.decode('utf-8', 'replace').rstrip())
        except Exception:
            pass

    def _note(self, level, text):
        if len(self.log) >= MAX_LOG:
            del self.log[0]
        self.log.append((level, text))

    #: How long to wait for the interface to answer one message. An
    #: application reading a folder or saving a file takes a moment; one
    #: that is stuck takes for ever, and an interface has to be able to
    #: tell the two apart.
    PATIENCE = 8.0

    def tell(self, kind, **rest):
        """Say what the user did, and wait for the interface to answer.

        Every message changes the screen, so this waits for the next one -
        an interface that sent a key press and then read the screen would
        otherwise read the screen from before it.

        **Answers whether one really came.** Silence and "nothing
        changed" look identical from the outside and mean opposite
        things: one is a button that did its work quietly, the other is
        an application still busy - or stuck - and the interface showing
        a screen that is no longer true.
        """
        if self.process is None or self.ended.is_set():
            return False
        self.changed.clear()
        try:
            with self._writing:
                self.process.stdin.write(wire.pack(kind, **rest))
                self.process.stdin.flush()
        except Exception:
            self.ended.set()
            return False
        return self.changed.wait(self.PATIENCE)

    # -------------------------------------------------------------- stop
    def ask_report(self):
        """What it has asked for so far. Answered into `unknown`."""
        self.tell('report')
        return list(self.unknown)

    def stop(self):
        """Close the application first and wait afterwards.

        The same order Cling arrived at: an application is a frame away
        from noticing it has been asked to stop, so what matters is that
        nothing it does later is answered.
        """
        try:
            self.tell('quit')
        except Exception:
            pass
        if self.process is None:
            return
        try:
            self.process.stdin.close()
        except Exception:
            pass
        if not self.ended.wait(1.5):
            try:
                self.process.kill()
            except Exception:
                pass
        # And reaped. An application that hung before it described
        # anything - a browser waiting on a web view - is killed rather
        # than waited for, and a killed process that is never waited on
        # stays a zombie for as long as Titan runs.
        try:
            self.process.wait(timeout=2.0)
        except Exception:
            pass
        for pipe in ('stdout', 'stderr', 'stdin'):
            try:
                stream = getattr(self.process, pipe, None)
                if stream is not None:
                    stream.close()
            except Exception:
                pass
        self.status = self.status or 'finished'
        self.ended.set()


def _titan_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(
        os.path.dirname(__file__))))


def _python():
    try:
        from src.titan_core.app_manager import get_python_executable
        found, _problem = get_python_executable()
        if found:
            return found
    except Exception:
        pass
    return sys.executable


def _last_words(log):
    for level, text in reversed(log or []):
        if level == 'stderr' and text.strip():
            return text.strip()
    return ''


#: What the child runs. `runpy.run_path(..., run_name='__main__')` is what
#: `app_manager` uses, and for the same reason: plain `exec` leaves
#: `__file__` undefined, which breaks any application that reads its own
#: folder at import time - and most of Titan's do.
_BOOT = '''\
import sys
sys.path.insert(0, r"%(titan)s")
sys.path.insert(0, r"%(folder)s")
sys.path.insert(0, r"%(shim)s")
sys.argv = [r"%(entry)s"]
import wx
try:
    import runpy
    runpy.run_path(r"%(entry)s", run_name="__main__")
except SystemExit:
    pass
except BaseException:
    import traceback
    traceback.print_exc()
finally:
    try:
        wx.RUNTIME.say("gone")
    except Exception:
        pass
'''
