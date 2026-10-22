# -*- coding: utf-8 -*-
"""Components written in another language.

Titan's component manager loads ``init.py``; a component folder with
``init.lua`` (or ``init.rb``, ``init.js``, ``init.ps1``...) instead is skipped
with "No init file found". This module finds those, and runs them inside
Titan's process the way a Python component runs:

* **Lua** runs on a thread of its own on this component's interpreter, so a
  component never blocks Titan's window. Everything Lua does is serialised on
  that one thread (the interpreter is not thread-safe). ``initialize()`` and
  ``shutdown()`` are called if the script defines them, and
  ``titan.add_menu(label, function)`` puts an entry in the Components menu.
* **anything else** runs as a child process speaking the same line protocol
  as an application, for as long as Titan runs; a menu entry it declares
  arrives as ``{"type": "menu", "label": ...}`` from ``next_event``.

Menu entries may also be declared in ``__component__.TCE`` (``menu = A; B``,
``menu_pl = ...``), which is the only way that is certain to be there before
Titan builds its menu bar - a child process answers when it answers.

Speech, sound and actions are asked of Titan directly (no bus: this is
Titan's own process), and dialogs are marshalled onto Titan's GUI thread.
"""

import configparser
import os
import queue
import threading
import traceback

from . import runtimes
from .api import TitanAPI, gui_caller
from .guests import LuaGuest, ProcessGuest, failure_text
from .i18n import _, language

_running = {}           # folder -> ForeignComponent


def _log(text):
    print('[polyglot] %s' % text)


def titan_call(addon, action, **args):
    from src.titan_core import actions
    return actions.run(addon, action, **args)


def _manifest(folder):
    config = configparser.ConfigParser()
    try:
        config.read(os.path.join(folder, '__component__.TCE'), encoding='utf-8')
    except Exception:
        pass
    return config


def init_file(folder):
    """The component's ``init.<ext>`` in a language a runtime answers."""
    if any(os.path.isfile(os.path.join(folder, n))
           for n in ('init.py', 'init.pyc')):
        return None, None
    for runtime in runtimes.all_runtimes():
        for ext in runtime.extensions:
            path = os.path.join(folder, 'init' + ext)
            if os.path.isfile(path):
                return path, runtime
    return None, None


class _LuaWorker(threading.Thread):
    """The one thread a Lua component ever runs on."""

    def __init__(self, name):
        threading.Thread.__init__(self, name='PolyglotLua:' + name, daemon=True)
        self.jobs = queue.Queue()

    def run(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            function, done, box = job
            try:
                box['value'] = function()
            except BaseException as error:              # noqa: B902
                box['error'] = error
            finally:
                done.set()

    def submit(self, function, wait=None):
        done = threading.Event()
        box = {}
        self.jobs.put((function, done, box))
        if wait is not None:
            done.wait(wait)
        return done, box


class ForeignComponent(object):
    def __init__(self, folder, path, runtime, manager):
        self.folder = folder
        self.path = path
        self.runtime = runtime
        self.manager = manager
        self.name = os.path.basename(folder.rstrip('\\/'))
        self.api = TitanAPI(folder, self.name, kind='component',
                            runtime_id=runtime.id, titan_call=titan_call,
                            on_gui=gui_caller(), log=self.log, ident=self.name)
        self.api.menu_handler = self._add_menu
        self.guest = None
        self.worker = None
        self.menus = []
        self.error = ''

    def log(self, text):
        _log('%s: %s' % (self.name, text))

    def _add_menu(self, label, function=None):
        if label in self.menus:
            return
        self.menus.append(label)

        def pressed(event=None, label=label, function=function):
            if function is not None and self.worker is not None:
                self.worker.submit(lambda: self.guest.runtime.call(function))
            else:
                self.api.post({'type': 'menu', 'label': label})
        try:
            self.manager.register_menu_function(label, pressed)
        except Exception as error:
            self.log('menu entry refused: %s' % error)

    def _declared_menus(self):
        config = _manifest(self.folder)
        if not config.has_section('component'):
            return
        lang = language()
        text = (config.get('component', 'menu_' + lang, fallback='') or
                config.get('component', 'menu', fallback=''))
        for label in [part.strip() for part in text.split(';')]:
            if label:
                self._add_menu(label)

    def _exited(self, code, error):
        if code:
            self.error = error or str(code)
            self.log('stopped: %s' % self.error)
            try:
                import wx
                wx.CallAfter(wx.MessageBox,
                             failure_text(self.name, code, error), self.name,
                             wx.OK | wx.ICON_ERROR)
            except Exception:
                pass

    def start(self):
        self._declared_menus()
        if self.runtime.inprocess:
            self.worker = _LuaWorker(self.name)
            self.worker.start()

            def load():
                self.guest = LuaGuest(self.api, self.path, self.log,
                                      self._exited)
                titan = self.guest.runtime.get_global('titan')
                # Lua's add_menu takes the function to run as well.
                titan.raw_set('add_menu', lambda label, fn=None:
                              self._add_menu(str(label), fn) or True)
                self.guest.runtime.run_file(self.path)
            done, box = self.worker.submit(load, wait=5.0)
            if 'error' in box:
                self.error = str(box['error'])
                self.log(traceback.format_exception_only(
                    type(box['error']), box['error'])[-1].strip())
                return False
            return True
        if not self.runtime.available():
            self.error = self.runtime.why_not()
            self.log(self.error)
            return False
        command = self.runtime.prepare(self.path, log=self.log)
        self.guest = ProcessGuest(self.api, self.path, self.log, self._exited,
                                  command, env=self.runtime.environment(
                                      self.path))
        self.guest.start()
        return True

    def call_hook(self, name):
        if self.worker is None or self.guest is None:
            return
        self.worker.submit(lambda: self.guest.call_global(name), wait=3.0)

    def stop(self):
        if self.worker is not None:
            self.call_hook('shutdown')
            self.api.exit(0)
            self.worker.jobs.put(None)
        elif self.guest is not None:
            self.guest.stop()


def discover():
    """{folder name: (folder, init file, runtime)} for enabled components."""
    try:
        from src.platform_utils import discover_data_entries
        entries = discover_data_entries('components')
    except Exception as error:
        _log('cannot list components: %s' % error)
        return {}
    out = {}
    for name, folder in entries.items():
        if not os.path.isdir(folder):
            continue
        path, runtime = init_file(folder)
        if not path:
            continue
        config = _manifest(folder)
        try:
            status = config.getint('component', 'status', fallback=0)
        except ValueError:
            status = 1
        if status == 0:
            out[name] = (folder, path, runtime)
    return out


def start_all(manager):
    started = []
    for name, (folder, path, runtime) in discover().items():
        if name in _running:
            continue
        component = ForeignComponent(folder, path, runtime, manager)
        try:
            ok = component.start()
        except Exception as error:
            component.error = str(error)
            component.log(traceback.format_exc())
            ok = False
        _running[name] = component
        if ok:
            started.append(name)
    return started


def initialize_all():
    for component in list(_running.values()):
        component.call_hook('initialize')


def stop_all():
    for component in list(_running.values()):
        try:
            component.stop()
        except Exception:
            pass
    _running.clear()


def running():
    return dict(_running)
