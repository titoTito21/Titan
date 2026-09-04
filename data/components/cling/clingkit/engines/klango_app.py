# -*- coding: utf-8 -*-
"""The engine that runs the application's OWN Klango code.

Every other engine in this package re-creates a genre from an application's
data. This one does not re-create anything: it loads the application's own Lua
out of its own package and runs Klango's own `main()`.

**It runs on a thread of its own, and that is not an optimisation.** Klango's
`app:loop()` does not return - it IS the game, from the first frame to the last
- so calling it from the window's thread would freeze Titan for as long as the
player was playing. So the application gets a thread, the window feeds it keys
and reads what it has said, and stopping it is a flag the frame calls notice.
"""

import threading

from .base import Engine


class KlangoEngine(Engine):
    """A Klango application, running its own code."""

    LABEL = 'application'

    #: How long `stop()` waits for the application to leave its own loop before
    #: giving up on it. A game that will not stop must not hold the window.
    STOP_WAIT = 2.0

    def __init__(self, host):
        Engine.__init__(self, host)
        self.session = None
        self.thread = None
        self.error = ''
        self._done = threading.Event()

    # ------------------------------------------------------------ lifetime
    def start(self):
        from .. import klango

        self.running = True
        try:
            self.session = klango.KlangoSession(self.host)
        except Exception as error:
            self._fail('the emulator could not be built: %s' % error)
            return
        if not self.session.lib_root:
            self._fail("Klango's platform library (llib) is not installed, so "
                       "this application's own code has nothing to run on")
            return

        self.thread = threading.Thread(target=self._run, name='cling-klango',
                                       daemon=True)
        # Klango's library is a real program with a real call chain, and a
        # tree-walking interpreter spends several Python frames on each of its
        # own - so the thread it runs on gets a stack to match.
        try:
            threading.stack_size(64 * 1024 * 1024)
        except (ValueError, RuntimeError):
            pass
        self.thread.start()

    def _run(self):
        try:
            self.session.start()
        except Exception as error:
            self.error = str(error)
        finally:
            for line in self.session.report():
                self.host.messages.append(line)
            self._done.set()
            self.running = False

    def _fail(self, reason):
        self.error = reason
        self.finished_reason = reason
        self.running = False
        self.host.show(reason)

    def stop(self):
        """Close the application: stop it, and stop what it is playing.

        The order matters and is the whole of what "closing the window
        silences it" means. `stopping` is a flag the application's own frame
        notices, and it can be a frame - or a long Lua call - away from
        noticing; a game left playing its background music for those two
        seconds, and one that never reached a frame at all played it for
        ever. So the host is CLOSED first: what is playing stops now, and
        nothing the application asks for afterwards is answered, however late
        it arrives. Then the thread is asked to leave, and waited for.
        """
        if self.session is not None:
            self.session.stopping = True
        try:
            self.host.close()
        except Exception:
            pass
        if self.thread is not None and self.thread.is_alive():
            self._done.wait(self.STOP_WAIT)
        self.running = False
        Engine.stop(self)

    # --------------------------------------------------------------- input
    def key(self, name, modifiers=()):
        """One press: the key goes down now and comes up at the end of its
        frame, which is what `k_KeyJustPressed` is asking about."""
        return self._reach(lambda: self.session.press(name))

    def key_down(self, name, modifiers=()):
        """The key is HELD until `key_up`.

        A Klango application polls the keyboard every frame, so holding an
        arrow to walk and holding Alt to reach a menu are real: the press and
        the release are two different events and the platform can tell.
        """
        return self._reach(lambda: self.session.key_down(name))

    def key_up(self, name, modifiers=()):
        return self._reach(lambda: self.session.key_up(name))

    def keys_released(self):
        """Let go of everything - the window has lost the keyboard."""
        if self.session is not None:
            self.session.keys.clear()

    def _reach(self, act):
        if self.session is None or not self.running:
            return False
        if self.thread is not None and not self.thread.is_alive():
            return False
        return bool(act())

    def tick(self, now=None):
        if self.thread is not None and not self.thread.is_alive():
            self.running = False

    # ------------------------------------------------------------- reading
    def status(self):
        if self.error:
            return self.error
        if self.session is None:
            return ''
        if self.thread is not None and self.thread.is_alive():
            return '%s (%d file(s) of its own code)' % (
                self.host.app.name(self.host.language), len(self.session.loaded))
        return self.host.app.name(self.host.language)

    def help_text(self):
        own = self.host.text('help')
        if own:
            return own
        return ('This is the application running its own code. Its keys are '
                'its own; Escape leaves.')


# The names Cling's windows use and the names Klango's key system uses are
# reconciled in one place - `klango/keyboard.py`'s `ALIASES` - because the
# scan code and the virtual key for a key are different numbers and both are
# needed. There is deliberately no second table here.
