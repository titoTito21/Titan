# -*- coding: utf-8 -*-
"""The platform under a TCE application when its interface is somewhere else.

An application is not modified and does not know: it goes on being an
ordinary wxPython program and this is what its `import wx` reaches. The
same idea as Cling under a Klango application and the Elten port under an
`.eltenapp` - do not rewrite the program, put a platform under it.

Three things carry the whole design:

- **Layout is thrown away, deliberately.** A sizer says where a button sits
  on a rectangle, and an interface made of speech has no rectangle.
  `BoxSizer` and its whole family are a sink here, which is a fifth of
  everything Titan's applications call.
- **A control's NAME is its label.** Titan's applications call `SetName` on
  every control precisely because they are written for people who cannot
  see them, so the accessible name is the best label there is - better than
  the button's own text, which is often abbreviated. Name first, then the
  label, then what kind of thing it is.
- **What is not here answers rather than raising.** 98 of the 274 wx names
  Titan's applications use are used exactly ONCE, and a shim that raises on
  the first one it has not got is a shim that never finishes. An unknown
  name is a recording no-op and the application carries on being wrong
  about one thing instead of stopping - the rule Cling's `report()` and the
  Elten port's `__index` both arrived at, from the same place.
"""

import os
import sys
import threading
import time

#: The reader thread puts this when the wire has closed.
_ENDED = object()

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')))

try:
    from src.app_ui import model, wire
except Exception:                                    # standalone / tests
    import importlib.util

    def _load(name, filename):
        here = os.path.join(os.path.dirname(__file__), '..', '..', filename)
        spec = importlib.util.spec_from_file_location(name, os.path.abspath(here))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    model = _load('_app_ui_model', 'model.py')
    wire = _load('_app_ui_wire', 'wire.py')


class Runtime(object):
    """The one of these there is. Holds the controls, the screens and the
    wire, and is the loop the application's `MainLoop` really runs."""

    def __init__(self):
        self.controls = {}
        self.screens = []              # the stack; the last one is showing
        self.put_away = None           # hidden, and the way back to it
        self.next_id = 0
        self.running = False
        self.quitting = False
        self.pending = []              # CallAfter, drained on the loop
        self.timers = []               # what is waiting to tick
        self._incoming = None          # what the reader thread has read
        self.refused = []              # what the application asked for and
        self.unknown = []              # what wx name it wanted
        self.modal_result = {}
        self.lock = threading.RLock()
        self._out = None
        self._in = None
        self._dirty = True

    # ---------------------------------------------------------- the wire
    def open_wire(self):
        """Take the real stdout away before the application can print on it.

        This is the trap the Elten port documents and it is the same one:
        an application's own `print` on the protocol stream corrupts it and
        the failure reads like a Titan bug rather than like a stray line.
        """
        if self._out is not None:
            return
        self._out = os.fdopen(os.dup(sys.stdout.fileno()), 'wb', 0)
        self._in = sys.stdin.buffer
        sys.stdout = sys.stderr

    def say(self, kind, **rest):
        if self._out is None:
            return
        try:
            self._out.write(wire.pack(kind, **rest))
        except Exception:
            pass

    # -------------------------------------------------------- the widgets
    def register(self, widget):
        with self.lock:
            self.next_id += 1
            widget._id = self.next_id
            self.controls[widget._id] = widget
        return widget._id

    def forget(self, widget):
        with self.lock:
            self.controls.pop(getattr(widget, '_id', None), None)
        self.changed()

    def find(self, identifier):
        return self.controls.get(identifier)

    def changed(self):
        """Something about the interface moved. The screen is sent once,
        after the handler that changed it has finished - an application
        changes six things to answer one key press and sending six screens
        would be six announcements."""
        self._dirty = True

    # -------------------------------------------------------- the screens
    def push(self, window):
        self.screens.append(window)
        if self.put_away is window:
            self.put_away = None
        self.changed()

    def pop(self, window):
        if window in self.screens:
            self.screens.remove(window)
            self.put_away = window
        self.changed()

    def showing(self):
        return self.screens[-1] if self.screens else None

    #: The control id of the one button on the "it put itself away"
    #: screen. Negative, so it can never collide with a real control.
    SHOW_AGAIN = -1

    def describe(self):
        """What is on the screen - and something is ALWAYS on it while the
        application is running.

        **An application with no window open is not an application with
        nothing to say.** The organiser's "minimise to system tray" hides
        its only window, and there is no tray here: the screen stack went
        empty, this answered None, nothing was sent, and every message
        from then on waited out its whole timeout against an application
        that was alive and perfectly well. Silence is the one answer an
        interface cannot do anything with, so it says what happened and
        offers the way back - which is what a tray icon is for.
        """
        window = self.showing()
        if window is not None:
            return window._describe()
        if self.put_away is None or not getattr(self.put_away, '_alive', False):
            return None
        title = self.put_away.label() or ''
        return {'id': 0, 'kind': 'window', 'title': title,
                'controls': [
                    {'id': self.SHOW_AGAIN - 1, 'kind': 'label',
                     'label': 'This application has put its window away.'},
                    {'id': self.SHOW_AGAIN, 'kind': 'button',
                     'label': 'Show it again', 'default': True}],
                'menus': [], 'focus': self.SHOW_AGAIN, 'modal': False}

    def send_screen(self):
        described = self.describe()
        if described is not None:
            self.say('screen', screen=described)
        self._dirty = False
        return described is not None

    # ----------------------------------------------------------- the loop
    def run(self, until=None):
        """Read what the user did, do it, and say what the interface is now.

        `until` is a callable answering True when a nested loop is over -
        which is what `ShowModal` is: wx blocks the caller inside the
        dialog, so this does too, or an application that opens a dialog and
        reads its fields afterwards would read them before they were filled.
        """
        # **The screen is sent when this is about to WAIT, and at no
        # other time.** Sending it after handling a message instead is
        # nearly the same thing and wrong in two ways that both reach the
        # user as an interface that has hung: a nested loop that is
        # leaving would announce the dialog it had just left, and a
        # message answered from INSIDE a nested loop - a `CallAfter` that
        # opened one - left the outer caller waiting out its whole
        # timeout for a screen that had already been sent by somebody
        # else. Saying "this is what is showing" immediately before
        # blocking cannot be early or late: it is the definition of what
        # is showing.
        self.running = True
        self._start_reading()
        while True:
            if self.quitting:
                break
            if until is not None and until():
                break
            self.send_screen()
            # **The wait has a deadline, so a timer can really tick.**
            # Blocking on the pipe until the user does something meant an
            # application waiting on a timer waited for ever - which for
            # the browser, whose engine reports itself on one, was an
            # application that never showed anything at all. The read is
            # on a thread of its own; everything the application runs
            # still happens here, on the one thread it was started on.
            raw = self._next(self._until_a_timer_is_due())
            if raw is _ENDED:
                break
            if raw is None:
                self._tick()
                continue
            message = wire.unpack(raw)
            if message is None:
                continue
            try:
                self._act(message)
            except Exception as error:
                self.failed(error)
            self._drain()
            self._tick()
        self.running = False

    # ---------------------------------------------------------- the clock
    def add_timer(self, timer):
        with self.lock:
            if timer not in self.timers:
                self.timers.append(timer)

    def drop_timer(self, timer):
        with self.lock:
            if timer in self.timers:
                self.timers.remove(timer)

    def _until_a_timer_is_due(self):
        """How long this may wait, or None for as long as it likes."""
        now = time.time()
        due = [timer.due for timer in list(self.timers)
               if getattr(timer, 'due', None) is not None]
        if not due:
            return None
        # Never busy-wait, and never sleep through one.
        return max(0.01, min(due) - now)

    def _tick(self):
        now = time.time()
        for timer in list(self.timers):
            when = getattr(timer, 'due', None)
            if when is None or when > now:
                continue
            try:
                timer.fire(now)
            except Exception as error:
                self.failed(error)
        self._drain()

    # ----------------------------------------------------------- the read
    def _start_reading(self):
        if self._incoming is not None:
            return
        import queue
        self._incoming = queue.Queue()

        def read():
            try:
                for raw in wire.lines(self._in):
                    self._incoming.put(raw)
            except Exception:
                pass
            self._incoming.put(_ENDED)

        threading.Thread(target=read, name='app-ui-wire', daemon=True).start()

    def _next(self, timeout):
        import queue
        try:
            return self._incoming.get(timeout=timeout) if timeout is not None \
                else self._incoming.get()
        except queue.Empty:
            return None

    def _drain(self):
        """Whatever `CallAfter` queued. An application does its slow work on
        a thread and comes back to the interface this way - 105 call sites
        across Titan's applications - so a loop that never drained would
        make every download, save and refresh invisible."""
        while True:
            with self.lock:
                if not self.pending:
                    return
                work, args, kwargs = self.pending.pop(0)
            try:
                work(*args, **kwargs)
            except Exception as error:
                self.failed(error)

    def later(self, work, *args, **kwargs):
        with self.lock:
            self.pending.append((work, args, kwargs))

    def _act(self, message):
        what = str(message.get('do') or '')
        if what == 'quit':
            self.report()
            self.quitting = True
            return
        if what == 'report':
            self.report()
            return
        if what == 'read':
            self.changed()
            return
        if what == 'press':
            if message.get('control') == self.SHOW_AGAIN:
                if self.put_away is not None:
                    self.put_away.Show(True)
                return
            target = self.find(message.get('control'))
            if target is not None:
                target._pressed(message)
            return
        if what == 'set':
            target = self.find(message.get('control'))
            if target is not None:
                target._set_from_user(message.get('value'))
            return
        if what == 'close':
            window = self.showing()
            if window is not None:
                window._closed_by_user()
            return
        if what == 'key':
            key = str(message.get('key') or '')
            # **A key can be aimed at a CONTROL, not only at the window.**
            # `_key` reaches the window's own handlers, which is where an
            # application binds F5 and its own letters - and it is not
            # where a field is typed into. Without a target there was no
            # way at all to put a character into a described text control
            # (only `set`, which replaces the whole value), so an
            # interface rendering this application could offer no edit
            # mode: it had to ask for the text in a dialog of its own.
            named = message.get('control')
            if named is not None:
                target = self.find(named)
                if target is not None and hasattr(target, '_typed'):
                    target._typed(key)
                    return
                if target is not None:
                    target._key(key) if hasattr(target, '_key') else None
                    return
            window = self.showing()
            if window is not None:
                window._key(key)
            return

    # -------------------------------------------------- what it could not do
    def failed(self, error):
        """**A handler that raised is a fault, and a fault has to be
        findable.** Announced only, it reached a channel nothing renders:
        `on_save` raising halfway through meant `EndModal` was never
        reached, the dialog stayed up, and the Save button read as a
        button that did nothing - with nothing anywhere to say otherwise.
        So it is written to stderr as well, which is what `app.log`
        reads back.
        """
        import traceback
        text = '%s: %s' % (type(error).__name__, error)
        self.say('said', text=text)
        try:
            sys.stderr.write('[app_ui] %s\n%s' % (text, traceback.format_exc()))
            sys.stderr.flush()
        except Exception:
            pass

    def refuse(self, what, detail=''):
        """Something wx offers that this cannot be. Recorded and said, never
        raised: an application that asks for a web view should lose the web
        view, not the application."""
        entry = {'what': str(what), 'detail': str(detail)}
        if entry not in self.refused:
            self.refused.append(entry)
            self.say('refused', what=entry['what'], detail=entry['detail'])

    def note_unknown(self, name):
        if name not in self.unknown:
            self.unknown.append(name)

    def report(self):
        """Everything the application asked wx for that is not here.

        The one thing that makes finishing this possible: without it,
        working out what an application still needs is reading its source
        and guessing, and with it the answer is a list. Cling's `report()`
        and the Elten port's `report()` exist for exactly this and were
        the difference between a subsystem that could be finished and one
        that could not.
        """
        self.say('report', unknown=list(self.unknown),
                 refused=list(self.refused))


RUNTIME = Runtime()
