# -*- coding: utf-8 -*-
"""One run of one application: the host, the engine and the clock between them.

The session is what the window drives and what a test drives, and it is
deliberately the same object in both cases.  A window gives it a wx timer and
real keys; a test gives it a clock it controls and a list of key names, and
plays a whole game through in a millisecond.  That equivalence is the reason
the engines below never read the clock and never touch wx: an engine that did
either could only be tested by playing it.
"""

import threading
import time


class Session(object):
    """An application, running."""

    #: How often the surface asks the engine to advance. Fast enough that a
    #: mole with a one-second life is not a mole that appears and is gone.
    TICK_MS = 50

    def __init__(self, app, language='', surface=None, clock=None,
                 profile=None):
        from . import engines, host as host_module

        self.app = app
        self.language = language
        self.host = host_module.ClingHost(app, language, profile=profile,
                                          surface=surface, clock=clock)
        self.engine = engines.build(self.host)
        self.started = False
        self._lock = threading.RLock()

    # ------------------------------------------------------------ lifetime
    def start(self):
        with self._lock:
            if self.started:
                return self
            self.started = True
            try:
                self.engine.start()
            except Exception as error:
                self._blame(error)
        return self

    def stop(self):
        with self._lock:
            if not self.started:
                return
            self.started = False
            try:
                self.engine.stop()
            except Exception as error:
                print('[cling] %s did not stop cleanly: %s' % (self.app.id, error))
            try:
                self.host.close()
            except Exception:
                pass

    @property
    def running(self):
        return self.started and getattr(self.engine, 'running', False)

    # --------------------------------------------------------------- input
    def key(self, name, modifiers=()):
        if not self.started:
            return False
        try:
            return bool(self.engine.key(name, modifiers))
        except Exception as error:
            self._blame(error)
            return False

    def key_down(self, name, modifiers=()):
        return self._half('key_down', name, modifiers)

    def key_up(self, name, modifiers=()):
        return self._half('key_up', name, modifiers)

    def _half(self, which, name, modifiers):
        if not self.started:
            return False
        try:
            return bool(getattr(self.engine, which)(name, modifiers))
        except Exception as error:
            self._blame(error)
            return False

    def tick(self, now=None):
        if not self.started:
            return
        try:
            self.engine.tick(now)
        except Exception as error:
            self._blame(error)

    # ------------------------------------------------------------- reading
    def status(self):
        try:
            return self.engine.status() or ''
        except Exception:
            return ''

    def rows(self):
        try:
            return list(self.engine.rows() or ())
        except Exception:
            return []

    def help_text(self):
        try:
            return self.engine.help_text() or ''
        except Exception:
            return ''

    @property
    def messages(self):
        return self.host.messages

    def _blame(self, error):
        import traceback
        print('[cling] %s failed: %s' % (self.app.id, error))
        traceback.print_exc()
        try:
            self.host.show('%s: %s' % (self.app.id, error))
        except Exception:
            pass
        self.started = False


class FakeClock(object):
    """A clock a test moves by hand, so a level can be played in no time."""

    def __init__(self, start=0.0):
        self.value = float(start)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += float(seconds)
        return self.value


def play(app, keys=(), language='', seconds_per_key=0.0, clock=None):
    """Run an application through a list of keys. For tests and for the actions.

    Returns the finished session, so a caller can read what was said, what was
    played and where the game got to.
    """
    clock = clock or FakeClock()
    session = Session(app, language, clock=clock).start()
    for name in keys:
        session.key(name)
        if seconds_per_key and hasattr(clock, 'advance'):
            clock.advance(seconds_per_key)
            session.tick()
    return session


def now():
    return time.monotonic()
