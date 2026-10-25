# -*- coding: utf-8 -*-
"""Every kind of Titan add-on, written in another language.

An application, a game and a component are things Titan STARTS; every other
kind is something Titan CALLS: a statusbar applet is asked for its text every
few seconds, a widget is told to move, a TTS engine is handed a sentence, a
gamepad mode is handed a button, a shell add-on is asked for its menu
entries. So a program in another language has to be callable, and that is
this module.

Each kind's loader in Titan looks for a Python file (``init.py``,
``main.py``, ``__engine__.py``...). Polyglot writes that file as a stub of a
few lines (``stubs.py``) which calls :func:`bind`, and :func:`bind` fills the
stub's namespace with exactly the functions (or the class) that kind's loader
looks for. Each of them calls the function of the SAME NAME in the program.
Nothing in Titan is changed.

How Titan calls the program
---------------------------
* **Lua** runs in Titan's process on a thread of its own; its functions are
  called directly, and a function it RETURNS (a menu entry's action) is a
  callable Titan can keep.
* **Any other language** runs as a child process speaking the line protocol.
  A call from Titan arrives as an event from ``next_event``::

      {"type": "call", "id": 7, "name": "get_statusbar_item_text", "args": []}

  and is answered with ``reply(7, "12:30")``. The SDKs do this in
  ``serve(handlers)``, which also tells Titan which functions exist
  (``provide``). A function the program wants Titan to keep (a menu entry's
  action) is returned as ``{"__function": "name"}``.

Objects
-------
Titan hands add-ons objects (a launcher's API, a shell add-on's API, the
parent window, a Titan IM module's ``sounds``). They cross as handles,
``{"__handle": 3, "__type": "LauncherAPI"}`` (with the object's own fields
when it can describe itself), and the program calls their methods with
``host(handle, "method", [args])``. The objects every add-on of a kind has
are also reachable by name: ``host("sounds", "new_message")``.
"""

import configparser
import itertools
import json
import os
import queue
import threading
import time
import traceback

from . import runtimes
from .api import ApiError, TitanAPI
from .guests import LuaGuest, ProcessGuest

#: How long Titan waits for an answer before it carries on without one.
CALL_TIMEOUT = 15.0
#: How long a child process has to say which functions it answers.
PROVIDE_TIMEOUT = 5.0

_addons = {}            # (kind, folder) -> ForeignAddon
_addons_lock = threading.Lock()


def _log(text):
    print('[polyglot] %s' % text)


def _is_main_thread():
    try:
        import wx
        return wx.GetApp() is not None and wx.IsMainThread()
    except Exception:
        return threading.current_thread() is threading.main_thread()


class _Worker(threading.Thread):
    """The one thread a Lua add-on ever runs on."""

    def __init__(self, name):
        threading.Thread.__init__(self, name='PolyglotAddon:' + name,
                                  daemon=True)
        self.jobs = queue.Queue()

    def run(self):
        while True:
            job = self.jobs.get()
            if job is None:
                return
            function, done, box = job
            try:
                box['value'] = function()
            except BaseException as error:                  # noqa: B902
                box['error'] = error
            finally:
                done.set()

    def submit(self, function):
        done = threading.Event()
        box = {}
        self.jobs.put((function, done, box))
        return done, box


class _Waiting(object):
    """A call in flight to a child process."""

    def __init__(self):
        self.done = threading.Event()
        self.value = None
        self.error = None


class ForeignAddon(object):
    """One add-on in another language, callable from Titan."""

    def __init__(self, kind, folder, source, runtime, objects=None):
        self.kind = kind
        self.folder = os.path.abspath(folder)
        self.source = source
        self.runtime = runtime
        self.name = os.path.basename(self.folder.rstrip('\\/'))
        self.objects = dict(objects or {})
        self.error = ''
        self.guest = None
        self.worker = None
        self._handles = {}
        self._handle_ids = {}
        self._counter = itertools.count(1)
        self._calls = {}
        self._provided = None
        self._provided_event = threading.Event()
        self._gui_jobs = queue.Queue()
        #: The last calls Titan made into the program - which is how a
        #: check says a pad's button really reached the mode.
        import collections
        self.history = collections.deque(maxlen=100)
        self._gui_waiting = 0
        self.api = TitanAPI(self.folder, self.name, kind=kind,
                            runtime_id=runtime.id, titan_call=_titan_call,
                            on_gui=self._on_gui, log=self.log,
                            ident=self.name)
        self.api.bridge = self

    # ----------------------------------------------------------- plumbing
    def log(self, text):
        _log('%s %s: %s' % (self.kind, self.name, text))

    def _on_gui(self, function):
        """Run on wx's thread - which may be the very thread waiting for
        this add-on to answer, so it is handed the job instead of being
        queued behind itself."""
        try:
            import wx
        except Exception:
            return function()
        if wx.GetApp() is None or wx.IsMainThread():
            return function()
        done = threading.Event()
        box = {}

        def run():
            try:
                box['value'] = function()
            except BaseException as error:                  # noqa: B902
                box['error'] = error
            finally:
                done.set()
        if self._gui_waiting:
            self._gui_jobs.put(run)
        else:
            wx.CallAfter(run)
        done.wait()
        if 'error' in box:
            raise box['error']
        return box.get('value')

    def _wait(self, event, timeout):
        """Wait for ``event``; on wx's thread, do wx's work meanwhile.

        ``timeout`` None waits for as long as it takes (a launcher's whole
        life) - never a huge number, which Windows' wait refuses outright
        ("timeout value is too large") and turns a launcher into one that
        ends the moment it starts."""
        end = None if timeout is None else time.time() + timeout
        if not _is_main_thread():
            return event.wait(timeout)
        self._gui_waiting += 1
        try:
            import wx
            app = wx.GetApp()
        except Exception:
            app = None
        try:
            while not event.is_set():
                try:
                    job = self._gui_jobs.get(timeout=0.01)
                    job()
                except queue.Empty:
                    pass
                # What the program asks of Titan meanwhile (speech, an
                # action) is queued for this very thread; let it through.
                if app is not None:
                    try:
                        app.Yield(True)
                    except Exception:
                        pass
                if end is not None and time.time() >= end:
                    return event.is_set()
            return True
        finally:
            self._gui_waiting -= 1

    def _exited(self, code, error):
        if code:
            self.error = error or str(code)
            self.log('stopped: %s' % self.error)
        for waiting in list(self._calls.values()):
            waiting.error = self.error or 'the program ended'
            waiting.done.set()
        self._provided_event.set()

    # --------------------------------------------------------- starting
    def start(self):
        if self.runtime.inprocess:
            self.worker = _Worker(self.name)
            self.worker.start()

            def load():
                self.guest = LuaGuest(self.api, self.source, self.log,
                                      self._exited)
                self.guest.runtime.run_file(self.source)
            done, box = self.worker.submit(load)
            self._wait(done, CALL_TIMEOUT)
            if 'error' in box:
                self.error = str(box['error'])
                self.log(traceback.format_exception_only(
                    type(box['error']), box['error'])[-1].strip())
                return False
            self._provided_event.set()
            return True
        if not self.runtime.available():
            self.error = self.runtime.why_not()
            self.log(self.error)
            self._provided_event.set()
            return False
        command = self.runtime.prepare(self.source, log=self.log)
        env = self.runtime.environment(self.source)
        try:
            from .hooks import python_and_root
            env['TITAN_ROOT'] = python_and_root()[1]
        except Exception:
            pass
        self.guest = ProcessGuest(self.api, self.source, self.log,
                                  self._exited, command, env=env)
        self.guest.start()
        return True

    def stop(self):
        if self.worker is not None:
            self.worker.jobs.put(None)
            self.worker = None
        elif self.guest is not None:
            self.guest.stop()
        self.api.exit(0)

    # ------------------------------------------------------- functions
    def provided(self, names):
        self._provided = set(str(n) for n in names)
        self._provided_event.set()

    def has(self, name):
        """Does the program define ``name``?"""
        if self.runtime.inprocess:
            if self.guest is None:
                return False
            return self.guest.runtime.get_global(name) is not None
        self._wait(self._provided_event, PROVIDE_TIMEOUT)
        if self._provided is None:
            return False
        return name in self._provided

    def call(self, name, *args, **options):
        """Call the program's function ``name``. Never raises: a program that
        does not answer gives ``default``."""
        default = options.get('default')
        timeout = options.get('timeout', CALL_TIMEOUT)
        wait = options.get('wait', True)
        self.history.append((name, args))
        if self.guest is None or self.error:
            return default
        wired = [self.to_wire(a) for a in args]
        try:
            if self.runtime.inprocess:
                function = self.guest.runtime.get_global(name)
                if function is None:
                    return default
                return self.call_function(function, *args, default=default,
                                          timeout=timeout, wait=wait)
            if self._provided is not None and name not in self._provided:
                return default
            ident = next(self._counter)
            waiting = _Waiting()
            self._calls[ident] = waiting
            self.api.post({'type': 'call', 'id': ident, 'name': name,
                           'args': wired})
            if not wait:
                return default
            if not self._wait(waiting.done, timeout):
                self.log('%s did not answer in %ss' % (name, timeout))
                self._calls.pop(ident, None)
                return default
            self._calls.pop(ident, None)
            if waiting.error:
                self.log('%s: %s' % (name, waiting.error))
                return default
            return self.from_wire(waiting.value)
        except Exception as error:
            self.log('%s failed: %s' % (name, error))
            return default

    def call_function(self, function, *args, **options):
        """Call a Lua function the program handed Titan."""
        default = options.get('default')
        guest = self.guest
        lua_args = [guest.to_lua(self.to_wire(a)) for a in args]

        def run():
            with guest.lock:
                return guest.runtime.call(function, *lua_args)
        done, box = self.worker.submit(run)
        if not options.get('wait', True):
            return default
        if not self._wait(done, options.get('timeout', CALL_TIMEOUT)):
            self.log('a function did not answer in time')
            return default
        if 'error' in box:
            self.log('function failed: %s' % box['error'])
            return default
        return self.from_wire(guest.to_python(box.get('value')))

    def replied(self, ident, value, error):
        waiting = self._calls.get(ident)
        if waiting is None:
            try:
                waiting = self._calls.get(int(ident))
            except (TypeError, ValueError):
                waiting = None
        if waiting is None:
            return
        waiting.value = value
        waiting.error = error
        waiting.done.set()

    # ----------------------------------------------------------- values
    def handle(self, obj):
        key = id(obj)
        number = self._handle_ids.get(key)
        if number is None or self._handles.get(number) is not obj:
            number = next(self._counter)
            self._handles[number] = obj
            self._handle_ids[key] = number
        return number

    def to_wire(self, value, depth=0):
        """A value as the program sees it: JSON, or a handle to an object."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if depth > 8:
            return str(value)
        if isinstance(value, (list, tuple, set)):
            return [self.to_wire(v, depth + 1) for v in value]
        if isinstance(value, dict):
            return {str(k): self.to_wire(v, depth + 1) for k, v in value.items()}
        wired = {'__handle': self.handle(value),
                 '__type': type(value).__name__}
        describe = getattr(value, 'as_dict', None)
        if callable(describe):
            try:
                for key, item in (describe() or {}).items():
                    wired.setdefault(str(key), self.to_wire(item, depth + 1))
            except Exception:
                pass
        return wired

    def from_wire(self, value, depth=0):
        """What the program answered, as Titan uses it: a handle back to its
        object, a function reference to a callable."""
        if depth > 12:
            return value
        if isinstance(value, dict):
            if '__handle' in value:
                try:
                    return self._handles[int(value['__handle'])]
                except (KeyError, TypeError, ValueError):
                    return None
            if '__function' in value:
                return self._callable(str(value['__function']))
            return {k: self.from_wire(v, depth + 1) for k, v in value.items()}
        if isinstance(value, list):
            return [self.from_wire(v, depth + 1) for v in value]
        if self.runtime.inprocess and callable(value) \
                and type(value).__name__ == 'LuaFunction':
            function = value
            return lambda *a, **_k: self.call_function(function, *a)
        return value

    def _callable(self, name):
        def call(*args, **_kwargs):
            return self.call(name, *args)
        call.__name__ = name
        return call

    def _target(self, target):
        if isinstance(target, dict):
            target = target.get('__handle', target.get('name'))
        if isinstance(target, (int, float)) and not isinstance(target, bool):
            obj = self._handles.get(int(target))
            if obj is None:
                raise ApiError('There is no object %s.' % target)
            return obj
        name = str(target or '')
        if name.isdigit():
            return self._target(int(name))
        if name in self.objects:
            return self.objects[name]
        raise ApiError('There is no object called %r. Objects: %s.'
                       % (name, ', '.join(sorted(self.objects)) or 'none'))

    def host(self, target, method, args=None):
        obj = self._target(target)
        method = str(method or '')
        if not method or method.startswith('_'):
            raise ApiError('Say which method.')
        if not hasattr(obj, method):
            raise ApiError('%s has no %r.' % (type(obj).__name__, method))
        attribute = getattr(obj, method)
        if not callable(attribute):
            return self.to_wire(attribute)
        if isinstance(args, dict):
            result = attribute(**{k: self.from_wire(v)
                                  for k, v in args.items()})
        else:
            if args is None:
                args = []
            elif not isinstance(args, (list, tuple)):
                args = [args]
            result = attribute(*[self.from_wire(a) for a in args])
        return self.to_wire(result)


def _titan_call(addon, action, **args):
    from src.titan_core import actions
    return actions.run(addon, action, **args)


# --------------------------------------------------------------- manifests
def _read_manifest(folder, names, section=None):
    """{key: value} of whichever manifest the folder has."""
    for name in names:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        try:
            if name.endswith('.json'):
                with open(path, 'r', encoding='utf-8') as handle:
                    return {str(k): v for k, v in json.load(handle).items()}
            parser = configparser.ConfigParser(interpolation=None)
            parser.read(path, encoding='utf-8')
            wanted = section if parser.has_section(section or '') else (
                parser.sections()[0] if parser.sections() else None)
            return dict(parser.items(wanted)) if wanted else {}
        except Exception:
            return {}
    return {}


def _localised(values, key):
    from .i18n import language
    lang = language()
    for candidate in (key + '_' + lang, key, key + '_en', key + '_pl'):
        if values.get(candidate):
            return str(values[candidate])
    return ''


# ------------------------------------------------------------------ binding
def addon_for(kind, folder, source, objects=None):
    """The one :class:`ForeignAddon` of this folder, started."""
    key = (kind, os.path.normcase(os.path.abspath(folder)))
    with _addons_lock:
        addon = _addons.get(key)
        if addon is not None:
            addon.objects.update(objects or {})
            return addon
        runtime = runtimes.for_file(source)
        if runtime is None:
            raise RuntimeError('No language is registered for %s.'
                               % os.path.basename(source))
        addon = ForeignAddon(kind, folder, source, runtime, objects)
        _addons[key] = addon
    addon.start()
    return addon


def running():
    return dict(_addons)


def stop_all():
    with _addons_lock:
        items = list(_addons.values())
        _addons.clear()
    for addon in items:
        try:
            addon.stop()
        except Exception:
            pass


def bind(namespace, kind, stub_file, source_name):
    """Make the stub's module look, to Titan, like that kind's Python file."""
    folder = os.path.dirname(os.path.abspath(stub_file))
    source = os.path.join(folder, source_name)
    if not os.path.isfile(source):
        raise ImportError('%s is not there.' % source)
    binder = _BINDERS.get(kind)
    if binder is None:
        raise ImportError('Polyglot cannot run a %s.' % kind)
    binder(namespace, folder, source)
    namespace['POLYGLOT_SOURCE'] = source
    return namespace


# Every kind below defines in the stub's namespace exactly what that kind's
# loader in Titan looks for, under the same names, so a Lua or Ruby add-on is
# written with the same functions as a Python one.

def _bind_im_module(ns, folder, source):
    objects = {key: ns[key] for key in ('sounds', 'config', 'ui', 'buffers')
               if key in ns}
    addon = addon_for('im_module', folder, source, objects)

    def open(parent_frame=None):                          # noqa: A001
        # Titan's window must not wait for a whole conversation to end.
        addon.call('open', parent_frame, wait=False)

    def get_status_text():
        return str(addon.call('get_status_text', default='', timeout=2) or '')
    ns.update(open=open, get_status_text=get_status_text, polyglot_addon=addon)


class _Widget(object):
    """A widget in another language, as the Invisible UI drives one."""

    def __init__(self, addon, speak):
        self.addon = addon
        self.speak = speak
        self.view = None
        addon.call('create')

    def navigate(self, direction):
        answer = self.addon.call('navigate', direction, default=False)
        if isinstance(answer, list):
            return tuple(answer)
        return answer

    def activate_current_element(self):
        self.addon.call('activate_current_element')

    def get_current_element(self):
        return str(self.addon.call('get_current_element', default='') or '')

    def set_border(self):
        self.addon.call('set_border', wait=False)

    def speak_with_position(self, text, position=0.0, pitch_offset=0):
        self.speak(text, position=position, pitch_offset=pitch_offset)


def _bind_widget(ns, folder, source):
    addon = addon_for('widget', folder, source)
    manifest = _read_manifest(folder, ('applet.json',))

    def get_widget_info():
        info = addon.call('get_widget_info') if addon.has('get_widget_info') \
            else None
        if not isinstance(info, dict):
            info = {}
        info.setdefault('name', _localised(manifest, 'name') or addon.name)
        info.setdefault('type', manifest.get('type') or 'grid')
        return info

    def get_widget_instance(speak_func, view=None):
        widget = _Widget(addon, speak_func)
        widget.view = view
        return widget
    ns.update(get_widget_info=get_widget_info,
              get_widget_instance=get_widget_instance, polyglot_addon=addon)


def _bind_statusbar_applet(ns, folder, source):
    addon = addon_for('statusbar_applet', folder, source)
    manifest = _read_manifest(folder, ('applet.json',))

    def get_statusbar_item_info():
        info = addon.call('get_statusbar_item_info') \
            if addon.has('get_statusbar_item_info') else None
        if not isinstance(info, dict):
            info = {}
        info.setdefault('name', _localised(manifest, 'name') or addon.name)
        info.setdefault('update_interval', manifest.get('update_interval', 5))
        return info

    def get_statusbar_item_text():
        return str(addon.call('get_statusbar_item_text', default='',
                              timeout=3) or '')

    def on_statusbar_item_activate(parent_frame=None):
        addon.call('on_statusbar_item_activate', parent_frame, wait=False)
    ns.update(get_statusbar_item_info=get_statusbar_item_info,
              get_statusbar_item_text=get_statusbar_item_text,
              on_statusbar_item_activate=on_statusbar_item_activate,
              polyglot_addon=addon)


def _bind_launcher(ns, folder, source):
    """A launcher runs its own interface for as long as Titan runs. Titan's
    wx loop has to run meanwhile (the launcher's dialogs are wx), so start()
    hands the launcher its API and returns; the launcher ending is Titan
    ending."""
    def start(api):
        import wx
        anchor = wx.Frame(None)          # keeps wx's loop running
        addon = addon_for('launcher', folder, source, {'api': api})
        ns['polyglot_addon'] = addon
        try:
            api.register_shutdown_callback(addon.stop)
        except Exception:
            pass

        def finished(*_args):
            def leave():
                try:
                    anchor.Destroy()
                except Exception:
                    pass
                try:
                    api.request_exit()
                except Exception:
                    wx.GetApp().ExitMainLoop()
            wx.CallAfter(leave)

        def run():
            addon.call('start', api, timeout=None)
            finished()
        threading.Thread(target=run, name='PolyglotLauncher',
                         daemon=True).start()
    ns.update(start=start)


def _bind_settings_interface(ns, folder, source):
    addon = addon_for('settings_interface', folder, source)

    def open_settings(api):
        addon.objects['api'] = api
        # A settings interface may keep its own loop going (a console asks
        # one question after another), so Titan does not wait for it.
        threading.Thread(target=lambda: addon.call('open_settings', api,
                                                   timeout=None),
                         name='PolyglotSettings', daemon=True).start()
        return True
    ns.update(open_settings=open_settings, polyglot_addon=addon)


def _bind_shell_addon(ns, folder, source):
    addon = addon_for('shell_addon', folder, source)
    try:
        from src.shell.addons import ALL_HOOKS
    except Exception:
        ALL_HOOKS = ('setup', 'teardown', 'on_shell_start', 'on_shell_stop',
                     'start_menu_items', 'explorer_menu_items',
                     'explorer_toolbar_items', 'explorer_context_items',
                     'explorer_columns', 'taskbar_bands',
                     'taskbar_menu_items', 'desktop_menu_items',
                     'open_start_menu', 'open_explorer')
    lists = {'start_menu_items', 'explorer_menu_items',
             'explorer_toolbar_items', 'explorer_context_items',
             'explorer_columns', 'taskbar_bands', 'taskbar_menu_items',
             'desktop_menu_items'}
    for name in ALL_HOOKS:
        # Only what the program defines: a shell surface asks an add-on
        # that HAS a hook, and one it does not have must stay absent.
        if not addon.has(name):
            continue

        def hook(*args, _name=name):
            default = [] if _name in lists else None
            answer = addon.call(_name, *args, default=default)
            if _name in lists and not isinstance(answer, list):
                return default
            return answer
        hook.__name__ = name
        ns[name] = hook
    ns['polyglot_addon'] = addon


def _bind_gamepad_mode(ns, folder, source):
    from src.controller import gamepad_mode_api
    addon = addon_for('gamepad_mode', folder, source,
                      {'gamepad': gamepad_mode_api})
    manifest = _read_manifest(folder, ('__mode__.TCE',), 'mode')
    display = _localised(manifest, 'name') or addon.name

    class PolyglotMode(gamepad_mode_api.GamepadMode):
        def get_display_name(self):
            return str(addon.call('get_display_name', default=display,
                                  timeout=2) or display)

        def on_activate(self, manager):
            addon.call('on_activate', manager)

        def on_deactivate(self, manager):
            addon.call('on_deactivate', manager)

        def handle_button(self, button_id):
            return bool(addon.call('handle_button', button_id, default=False,
                                   timeout=5))

        def handle_axis(self, axis_id, value):
            return bool(addon.call('handle_axis', axis_id, value,
                                   default=False, timeout=5))

        def handle_hat(self, x, y):
            return bool(addon.call('handle_hat', x, y, default=False,
                                   timeout=5))

        def handle_bumper(self, is_left):
            return bool(addon.call('handle_bumper', is_left, default=False,
                                   timeout=5))
    # The loader instantiates every GamepadMode subclass DEFINED in the
    # mode's own module, which is the stub.
    PolyglotMode.__module__ = ns.get('__name__', PolyglotMode.__module__)
    PolyglotMode.__qualname__ = 'PolyglotMode'
    PolyglotMode.polyglot_addon = addon
    ns.update(PolyglotMode=PolyglotMode, polyglot_addon=addon)


def _bind_tts_engine(ns, folder, source):
    from src.tts.base_engine import TitanTTSEngine
    addon = addon_for('tts_engine', folder, source)
    manifest = _read_manifest(folder, ('__engine__.TCE',), 'engine')
    ident = (manifest.get('id') or addon.name).strip().lower().replace(' ', '_')

    class PolyglotEngine(TitanTTSEngine):
        engine_id = ident
        engine_name = _localised(manifest, 'name') or addon.name
        engine_category = 'titantts'
        needs_lock_release = True

        def is_available(self):
            return bool(addon.call('is_available', default=True, timeout=5))

        def generate(self, text, pitch_offset=0):
            """The program answers a WAV file's path (or its bytes, base64)."""
            answer = addon.call('generate', text, pitch_offset, timeout=60)
            if not answer:
                return None
            try:
                from pydub import AudioSegment
                if isinstance(answer, dict) and answer.get('base64'):
                    import base64
                    import io
                    data = base64.b64decode(answer['base64'])
                    return AudioSegment.from_file(io.BytesIO(data),
                                                  format=answer.get('format',
                                                                    'wav'))
                path = str(answer)
                if not os.path.isabs(path):
                    path = os.path.join(folder, path)
                # The format named, or pydub asks ffmpeg even for a WAV.
                kind = os.path.splitext(path)[1].lstrip('.').lower() or 'wav'
                return AudioSegment.from_file(path, format=kind)
            except Exception as error:
                addon.log('generate: %s' % error)
                return None

        def get_voices(self):
            voices = addon.call('get_voices', default=[])
            return voices if isinstance(voices, list) else []

        def set_voice(self, voice_id):
            addon.call('set_voice', voice_id)

        def set_rate(self, rate):
            addon.call('set_rate', rate, wait=False)

        def set_pitch(self, pitch):
            addon.call('set_pitch', pitch, wait=False)

        def set_volume(self, volume):
            addon.call('set_volume', volume, wait=False)

        def stop(self):
            addon.call('stop', wait=False)

        @classmethod
        def get_config_fields(cls):
            fields = addon.call('get_config_fields', default=[])
            return fields if isinstance(fields, list) else []

        def configure(self, key, value):
            addon.call('configure', key, value)

        def get_config(self, key):
            return addon.call('get_config', key)

    engine = {}

    def get_engine():
        if 'it' not in engine:
            engine['it'] = PolyglotEngine()
        return engine['it']
    PolyglotEngine.__module__ = ns.get('__name__', PolyglotEngine.__module__)
    PolyglotEngine.polyglot_addon = addon
    ns.update(get_engine=get_engine, PolyglotEngine=PolyglotEngine,
              polyglot_addon=addon)


_BINDERS = {
    'im_module': _bind_im_module,
    'widget': _bind_widget,
    'statusbar_applet': _bind_statusbar_applet,
    'launcher': _bind_launcher,
    'settings_interface': _bind_settings_interface,
    'shell_addon': _bind_shell_addon,
    'gamepad_mode': _bind_gamepad_mode,
    'tts_engine': _bind_tts_engine,
}

#: Every kind Polyglot can run, with how it is run.
#: app/game run through Titan's app and game managers (hooks.py), component
#: through components.py, macro through the Macro Manager (hooks.py), the
#: rest through a Python entry and a binder here.
KINDS = ('app', 'game', 'component', 'macro') + tuple(_BINDERS)
