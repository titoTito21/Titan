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
        self.next_id = 0
        self.running = False
        self.quitting = False
        self.pending = []              # CallAfter, drained on the loop
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
        self.changed()

    def pop(self, window):
        if window in self.screens:
            self.screens.remove(window)
        self.changed()

    def showing(self):
        return self.screens[-1] if self.screens else None

    def describe(self):
        window = self.showing()
        if window is None:
            return None
        return window._describe()

    def send_screen(self):
        described = self.describe()
        if described is not None:
            self.say('screen', screen=described)
        self._dirty = False

    # ----------------------------------------------------------- the loop
    def run(self, until=None):
        """Read what the user did, do it, and say what the interface is now.

        `until` is a callable answering True when a nested loop is over -
        which is what `ShowModal` is: wx blocks the caller inside the
        dialog, so this does too, or an application that opens a dialog and
        reads its fields afterwards would read them before they were filled.
        """
        self.running = True
        if self._dirty:
            self.send_screen()
        for raw in wire.lines(self._in):
            message = wire.unpack(raw)
            if message is None:
                continue
            try:
                self._act(message)
            except Exception as error:
                self.say('said', text='%s: %s' % (type(error).__name__, error))
            self._drain()
            if self._dirty:
                self.send_screen()
            if self.quitting:
                break
            if until is not None and until():
                break
        self.running = False

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
                self.say('said', text='%s: %s' % (type(error).__name__, error))

    def later(self, work, *args, **kwargs):
        with self.lock:
            self.pending.append((work, args, kwargs))

    def _act(self, message):
        what = str(message.get('do') or '')
        if what == 'quit':
            self.quitting = True
            return
        if what == 'read':
            self.changed()
            return
        if what == 'press':
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
            window = self.showing()
            if window is not None:
                window._key(str(message.get('key') or ''))
            return

    # -------------------------------------------------- what it could not do
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


RUNTIME = Runtime()
