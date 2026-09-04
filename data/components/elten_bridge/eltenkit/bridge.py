# -*- coding: utf-8 -*-
"""One running Elten application: the process, the wire and the dispatch.

Copyright (C) 2026 titosoft. Part of the Elten API bridge, licensed under the
GNU General Public License version 3 or later; see `LICENSE` beside this
component.

The application runs in a Ruby process of its own and everything it asks the
platform for arrives here as a line of JSON. That process boundary is the
first half of "safe": an application that loops for ever, exhausts its stack
or segfaults a gem takes down a subprocess, not Titan - and closing the window
kills it, which is a guarantee no in-process interpreter can make.

The second half is this module's dispatch table. **An operation exists or it
does not**: there is no way for an application to name a Python attribute, a
module, a file outside its roots or a method Titan did not write down here.
Every handler validates what it was given rather than trusting the types, and
every one of them answers - a refusal is a reply saying no, never a hang,
because the application is blocked on it.

    Ruby  ->  {"id":7,"op":"alert","args":{"text":"..."}}
    Titan ->  {"id":7,"ok":true,"result":null}
    Titan ->  {"event":"key","name":"down"}

The rules that keep the wire honest:

* **A line is capped** (`MAX_LINE`). A runaway application must not be able to
  make Titan buffer without bound; a line longer than that ends the
  application with a sentence saying so.
* **stdout is the protocol and stderr is the log.** The Ruby side moves
  `$stdout` to stderr at boot precisely so an application's own `puts` cannot
  corrupt the stream, and this side reads them separately.
* **Every call is answered exactly once**, including the ones that raise: a
  handler that fell over without replying would leave the application blocked
  for ever on a dialog that never opens.
* **UI happens on the GUI thread.** The reader is a worker; anything that
  touches wx is marshalled and waited for, which is also what makes a modal
  dialog block the application the way Elten's does.
"""

import json
import os
import queue
import subprocess
import sys
import threading

from . import host as host_module
from . import package as package_module
from . import runtime as runtime_module

#: The longest line either side may send. Comfortably more than a dialog with
#: two thousand entries in it, and far less than memory.
MAX_LINE = 4 * 1024 * 1024

#: How long to wait for the process to leave after being asked, before it is
#: killed. An application in a tight loop never notices the ask.
STOP_WAIT = 3.0

#: How long a call from Ruby may occupy the GUI thread before the bridge
#: stops waiting for it. Nothing here should take a second; the ceiling is
#: for a dialog that somehow never returns, so the application gets an error
#: instead of hanging for ever.
CALL_TIMEOUT = 3600.0

#: How many log lines to keep from an application. Enough to see what went
#: wrong, bounded so a chatty application cannot fill memory.
MAX_LOG = 2000


class Application(object):
    """One running application. Started by `start`, stopped by `stop`."""

    def __init__(self, entry, paths, speaker=None, sounds=None,
                 translator=None, ui=None, language='en'):
        #: The catalogue entry - what is being run.
        self.entry = entry
        self.paths = paths
        self.language = language or 'en'
        self.speaker = speaker if speaker is not None else host_module.Speaker()
        self.sounds = sounds if sounds is not None else host_module.Sounds()
        #: Answers `translate`; None means "hand the string back".
        self.translator = translator
        #: What draws: dialogs, lists, progress. None means a headless run,
        #: which is what the tests use and what an action-API call gets.
        self.ui = ui

        self.process = None
        self.status = ''
        self.detail = ''
        self.log = []
        self.started = threading.Event()
        self.ended = threading.Event()
        #: Streams this application has open - a radio station, a podcast.
        #: A handle is a number in this table, never anything the
        #: application supplies, so one application cannot reach another's.
        self._streams = {}
        self._stream_next = 0
        self._stream_lock = threading.Lock()
        self._writing = threading.Lock()
        self._locks = {}
        self._lock_next = 0
        self._tasks = {}
        self._task_next = 0
        self._keys_held = set()
        self._watched = set()
        self._threads = []
        self._stopping = False

    # ------------------------------------------------------------- running
    def start(self):
        """Unpack if needed, then start the interpreter. Never raises."""
        try:
            interpreter = runtime_module.find()
        except runtime_module.RubyMissing as error:
            return self._fail(str(error))

        boot = os.path.join(runtime_module.component_root(), 'eapi', 'boot.rb')
        if not os.path.isfile(boot):
            return self._fail('the bridge is incomplete: eapi/boot.rb is missing')

        directory = self.paths.root('asset')
        if not directory or not os.path.isdir(directory):
            return self._fail('the application was not unpacked')

        manifest = json.dumps(self.entry.manifest, ensure_ascii=False)
        try:
            self.process = subprocess.Popen(
                [interpreter.path, '--disable-gems', boot, directory, manifest]
                if False else [interpreter.path, boot, directory, manifest],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, cwd=directory,
                env=interpreter.environment(),
                creationflags=_no_window(), bufsize=0)
        except OSError as error:
            return self._fail('the application could not be started: %s' % error)

        self._spawn(self._read_replies, 'elten-bridge-out')
        self._spawn(self._read_log, 'elten-bridge-err')
        return True

    def _spawn(self, target, name):
        thread = threading.Thread(target=target, name=name, daemon=True)
        self._threads.append(thread)
        thread.start()
        return thread

    def _fail(self, reason):
        self.status = 'failed'
        self.detail = reason
        self.ended.set()
        return False

    def running(self):
        return self.process is not None and self.process.poll() is None

    def stop(self, wait=STOP_WAIT):
        """Close the application and everything it was using.

        The order matters. The audio is closed FIRST so that what is playing
        stops now rather than in however long the process takes to notice;
        then the pipe is closed, which is what the Ruby side reads as "Titan
        has gone" and what releases anything blocked on a dialog; then, if it
        is still there, it is killed. A game in its own loop can be a whole
        frame from noticing, and an application waiting on a socket may never
        notice at all - neither may keep the window open.
        """
        self._stopping = True
        # A stream is audio and goes with the rest of it: a station left
        # playing after its window has gone is the worst kind of leak,
        # because the only way to stop it is to close Titan.
        with self._stream_lock:
            streams, self._streams = list(self._streams.values()), {}
        for stream in streams:
            try:
                stream.close()
            except Exception:
                pass
        try:
            self.sounds.close()
        except Exception:
            pass
        try:
            self.speaker.close()
        except Exception:
            pass
        if self.process is None:
            self.ended.set()
            return
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except Exception:
            pass
        try:
            self.process.wait(timeout=wait)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
        self.ended.set()

    # -------------------------------------------------------------- events
    def send_event(self, event, **fields):
        """Tell the application something happened. Never blocks on it.

        The first argument is `event` and not `name` on purpose: a control
        event carries a `name` of its OWN (`key_left`, `press`), and a
        parameter called `name` here collides with it - which is exactly
        what happened, and it took every keystroke in every form down with a
        `TypeError` raised inside a wx handler where nothing catches it.
        """
        message = {'event': str(event)}
        message.update(fields)
        self._write(message)

    def key_down(self, name, repeat=False):
        name = str(name or '')
        if not name:
            return
        self._keys_held.add(name)
        self.send_event('key', name=name, repeat=bool(repeat))

    def key_up(self, name):
        name = str(name or '')
        if not name:
            return
        self._keys_held.discard(name)
        self.send_event('key_up', name=name)

    def keys_released(self):
        """Let go of everything - the window lost the keyboard."""
        for name in list(self._keys_held):
            self.key_up(name)

    # ------------------------------------------------------------- the wire
    def _write(self, message):
        if self.process is None or self.process.stdin is None:
            return False
        try:
            line = json.dumps(message, ensure_ascii=False).encode('utf-8')
        except (TypeError, ValueError):
            return False
        if len(line) > MAX_LINE:
            return False
        with self._writing:
            try:
                self.process.stdin.write(line + b'\n')
                self.process.stdin.flush()
                return True
            except (OSError, ValueError):
                return False

    def _read_replies(self):
        stream = self.process.stdout
        try:
            for raw in _lines(stream):
                if raw is _TOO_LONG:
                    self.detail = ('the application sent a line longer than '
                                   'the bridge will read')
                    self.status = 'failed'
                    break
                try:
                    message = json.loads(raw.decode('utf-8'))
                except (UnicodeDecodeError, ValueError):
                    continue
                if not isinstance(message, dict):
                    continue
                self._handle(message)
        except Exception as error:
            self._note('bridge', 'the wire failed: %s' % error)
        finally:
            self.ended.set()

    def _read_log(self):
        stream = self.process.stderr
        try:
            for raw in _lines(stream):
                if raw is _TOO_LONG:
                    continue
                self._note('stderr', raw.decode('utf-8', 'replace').rstrip())
        except Exception:
            pass

    def _note(self, level, text):
        if len(self.log) >= MAX_LOG:
            del self.log[0]
        self.log.append((level, text))

    def _handle(self, message):
        """One message from the application.

        A call carries an id and gets exactly one reply, whatever happens -
        including an operation that does not exist, which is answered rather
        than ignored so an application written against a newer Elten finds
        out instead of hanging.
        """
        identifier = message.get('id')
        operation = str(message.get('op') or '')
        arguments = message.get('args')
        if not isinstance(arguments, dict):
            arguments = {}

        if identifier is None:
            handler = NOTIFICATIONS.get(operation)
            if handler is not None:
                try:
                    handler(self, arguments)
                except Exception as error:
                    self._note('bridge', '%s failed: %s' % (operation, error))
            return

        handler = OPERATIONS.get(operation)
        if handler is None:
            self._write({'id': identifier, 'ok': False,
                         'kind': 'unknown',
                         'error': ('this version of Titan does not implement '
                                   '%s' % operation)})
            return
        try:
            result = handler(self, arguments)
            self._write({'id': identifier, 'ok': True, 'result': result})
        except _Refused as error:
            self._write({'id': identifier, 'ok': False, 'kind': 'refused',
                         'error': str(error)})
        except host_module.PathRefused as error:
            self._note('refused', '%s: %s' % (operation, error))
            self._write({'id': identifier, 'ok': False, 'kind': 'refused',
                         'error': str(error)})
        except Exception as error:
            self._note('bridge', '%s raised: %s: %s'
                       % (operation, type(error).__name__, error))
            self._write({'id': identifier, 'ok': False, 'kind': 'error',
                         'error': '%s: %s' % (type(error).__name__, error)})

    # --------------------------------------------------------- the GUI side
    def _on_gui(self, call, default=None):
        """Run something on the GUI thread and wait for it.

        The reader is a worker and wx is not thread-safe, so anything that
        draws is marshalled. The wait is what makes a modal dialog modal for
        the APPLICATION as well as for the window - which is exactly Elten's
        contract: `confirm` does not return until the user has answered it.
        """
        if self.ui is None:
            return default
        answer = queue.Queue(1)

        def run():
            try:
                answer.put((True, call()))
            except Exception as error:
                answer.put((False, error))

        try:
            import wx
        except Exception:
            return default
        if wx.IsMainThread():
            run()
        else:
            wx.CallAfter(run)
        try:
            ok, value = answer.get(timeout=CALL_TIMEOUT)
        except queue.Empty:
            return default
        if not ok:
            raise value
        return value


_TOO_LONG = object()


def _lines(stream, limit=MAX_LINE):
    """Whole lines, refusing to buffer without bound.

    `readline` on a pipe will happily grow to whatever the far end sends,
    which for a process that is misbehaving is memory Titan does not get
    back. This yields a sentinel instead and lets the caller end it.
    """
    buffer = bytearray()
    while True:
        chunk = stream.read(65536)
        if not chunk:
            if buffer:
                yield bytes(buffer)
            return
        buffer.extend(chunk)
        while True:
            index = buffer.find(b'\n')
            if index < 0:
                break
            line = bytes(buffer[:index])
            del buffer[:index + 1]
            if line:
                yield line
        if len(buffer) > limit:
            yield _TOO_LONG
            return


def _no_window():
    if sys.platform != 'win32':
        return 0
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)


# ---------------------------------------------------------------------------
# The dispatch table. This IS the security boundary: what is not here cannot
# be reached, whatever the application asks for.
# ---------------------------------------------------------------------------
def _op_speak(app, args):
    text = args.get('text')
    said = app.speaker.say(text, args.get('position', 0.0),
                           args.get('pitch', 0.0),
                           args.get('interrupt', True), args.get('wait', False))
    # The same words, kept in the window. These applications are
    # self-voicing, so without this the window is an empty box to anybody
    # who is not listening to it.
    if app.ui is not None and hasattr(app.ui, 'say_on_screen'):
        try:
            app._on_gui(lambda: app.ui.say_on_screen(host_module._text(text)),
                        None)
        except Exception:
            pass
    return said


def _op_stop_speech(app, args):
    return app.speaker.stop()


def _op_speaking(app, args):
    return app.speaker.speaking()


#: The bridge's own few words, in the user's language. Cached because
#: `_()` is called per line by everything.
_OURS = {}


def _our_words(language):
    """The bridge's own catalogue - the handful of strings Titan builds
    rather than the application.

    Almost nothing needs this: every label, header and prompt an
    application shows comes from the application, already translated by
    its own `.mo`. These are the controls the bridge makes itself - the
    player's transport, the file tree's own menu, and what it asks before
    it changes somebody's disk - and without a catalogue of their own they
    were the only English on a Polish desktop.
    """
    if language in _OURS:
        return _OURS[language]
    import gettext
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        found = gettext.translation('elten_bridge',
                                    os.path.join(here, 'languages'),
                                    languages=[language], fallback=True)
    except Exception:
        found = None
    _OURS[language] = found
    return found


def _op_translate(app, args):
    text = host_module._text(args.get('text'))
    # The application's own words first - they are its own and it knows
    # them best - and the bridge's only for what the application has never
    # heard of.
    if app.translator is not None:
        try:
            answer = app.translator.gettext(text)
            if answer != text:
                return answer
        except Exception:
            pass
    ours = _our_words(app.language)
    if ours is not None:
        try:
            return ours.gettext(text)
        except Exception:
            pass
    return text


def _op_translate_plural(app, args):
    one = host_module._text(args.get('one'))
    other = host_module._text(args.get('other'))
    try:
        count = int(args.get('count', 1))
    except (TypeError, ValueError):
        count = 1
    if app.translator is None:
        return one if count == 1 else other
    try:
        return app.translator.ngettext(one, other, count)
    except Exception:
        return one if count == 1 else other


def _op_path(app, args):
    return app.paths.resolve(args.get('kind'), args.get('relative', ''))


def _op_lock(app, args):
    """Serialise writers of one file, as Elten guarantees.

    The lock is Titan's because Titan is the only side that can see every
    writer: two of an application's own threads, and the window's own
    handlers, all come through here.
    """
    path = str(args.get('path') or '')
    app._lock_next += 1
    token = app._lock_next
    held = app._locks.setdefault(path, threading.Lock())
    held.acquire()
    app._locks['#%d' % token] = (path, held)
    return token


def _op_unlock(app, args):
    key = '#%d' % host_module._handle(args.get('token'))
    entry = app._locks.pop(key, None)
    if entry is None:
        return False
    _path, held = entry
    try:
        held.release()
    except RuntimeError:
        return False
    return True


def _op_stream_open(app, args):
    """A URL to play - a radio station, a podcast episode."""
    stream = host_module.Stream(app.sounds.mixer, args.get('url'),
                                args.get('label') or '')
    if stream.error and not stream.opened:
        app._note('bridge', 'stream: %s' % stream.error)
        stream.close()
        return None
    with app._stream_lock:
        app._stream_next += 1
        handle = app._stream_next
        app._streams[handle] = stream
    answer = stream.status()
    answer['handle'] = handle
    return answer


def _op_stream_do(app, args):
    stream = app._streams.get(host_module._handle(args.get('handle')))
    if stream is None:
        return None
    what = str(args.get('do') or 'status')
    if what == 'play':
        stream.play()
    elif what == 'pause':
        stream.pause()
    elif what == 'seek':
        stream.seek(args.get('position', 0.0))
    elif what == 'volume':
        stream.set_volume(args.get('volume', 1.0))
    elif what == 'close':
        stream.close()
        with app._stream_lock:
            app._streams.pop(host_module._handle(args.get('handle')), None)
        return True
    return stream.status()


def _op_popup_menu(app, args):
    """Show the menu an application built, and answer which item was
    chosen - a list of positions, so a submenu is `[1, 0]`."""
    form = args.get('form')
    if form is None:
        return None
    return app._on_gui(
        lambda: app.ui.popup_menu(form, int(args.get('control') or 0),
                                  args.get('items') or []), None)


def _op_control_focus(app, args):
    """Put the keyboard on one control of a form that is showing."""
    form = args.get('form')
    index = args.get('control')
    if form is None or index is None:
        return False
    return bool(app._on_gui(lambda: app.ui.focus_control(form, int(index)),
                            False))


def _op_sound_asset(app, args):
    """Where a named sound really is, or None.

    Applications ask before they play - Solitaire's whole audio layer is
    optional - so this must answer None for something that is not there
    rather than refusing. What it will not do is look outside the package.
    """
    name = str(args.get('name') or '')
    if not name:
        return None
    for candidate in _sound_names(name):
        try:
            full = app.paths.resolve('asset', candidate)
        except host_module.PathRefused:
            return None
        if os.path.isfile(full):
            return full
    return None


def _sound_names(name):
    """The names Elten's applications use for one sound.

    They write `play_sound_from_asset("draw")` and ship `Audio/draw.ogg`, so
    the extension and the folder are both implied. The order is the order
    Elten resolves them in.
    """
    name = name.replace('\\', '/').lstrip('/')
    stem, extension = os.path.splitext(name)
    if extension:
        candidates = [name]
    else:
        candidates = ['%s%s' % (name, suffix)
                      for suffix in ('.ogg', '.wav', '.mp3', '.flac', '.opus')]
    found = []
    for candidate in candidates:
        found.append(candidate)
        if '/' not in candidate:
            found.append('Audio/%s' % candidate)
            found.append('audio/%s' % candidate)
            found.append('sounds/%s' % candidate)
    return found


def _op_sound_create(app, args):
    path = _op_sound_asset(app, args)
    if path is None:
        return None
    return app.sounds.create(path, bool(args.get('spatial')),
                             args.get('position', 0.0),
                             bool(args.get('loop')))


def _op_sound_play(app, args):
    return app.sounds.play(args.get('handle'), args.get('volume'),
                           args.get('position'), args.get('loop'))


def _op_sound_stop(app, args):
    return app.sounds.stop(args.get('handle'))


def _op_sound_playing(app, args):
    return app.sounds.playing(args.get('handle'))


def _op_sound_volume(app, args):
    return app.sounds.set_volume(args.get('handle'), args.get('volume', 1.0))


def _op_sound_position(app, args):
    return app.sounds.set_position(args.get('handle'), args.get('position', 0.0))


def _op_sound_pause(app, args):
    return app.sounds.pause(args.get('handle'), bool(args.get('paused', True)))


def _op_sound_close(app, args):
    return app.sounds.close_sound(args.get('handle'))


def _op_sound_pool_play(app, args):
    path = _op_sound_asset(app, args)
    if path is None:
        return None
    return app.sounds.pool_play(path, args.get('volume', 1.0),
                                args.get('max_voices',
                                         host_module.POOL_VOICES),
                                args.get('position', 0.0),
                                bool(args.get('loop')))


def _op_sound_pool_close(app, args):
    return app.sounds.close_pool()


def _op_play_cue(app, args):
    """`play_sound(name)` - one of Elten's interface cues.

    Titan's theme first: moving onto a row, choosing it, the end of a list,
    a dialog opening are all things this desktop already has a sound for,
    and the user picked it. Only if Titan has no opinion about the name does
    it fall through to the application's own file - so a mapping can replace
    a cue and can never lose one.
    """
    from . import cues as cues_module
    name = str(args.get('name') or '')
    position = args.get('position', 0.0)
    titan = cues_module.titan_cue(name)
    if titan:
        if app.sounds.mixer.cue(titan, position):
            return True
    own = _op_sound_asset(app, {'name': name})
    if own:
        return app.sounds.pool_play(own, args.get('volume', 1.0),
                                    host_module.POOL_VOICES, position)
    return False


def _op_key_held(app, args):
    """Is it down RIGHT NOW? A game asks inside its own frame - it walks
    while Left is held - so this is the live set, not a remembered event.

    A letter answers to both its spellings (`key_a` and `a`), because
    Elten's applications bind both.
    """
    wanted = str(args.get('name') or '').strip().lower()
    if not wanted:
        return False
    if wanted in app._keys_held:
        return True
    other = wanted[4:] if wanted.startswith('key_') else 'key_%s' % wanted
    return other in app._keys_held


def _op_app_name(app, args):
    return app.entry.name or app.entry.stem


def _op_app_description(app, args):
    return app.entry.description


def _op_app_version(app, args):
    return app.entry.version


def _op_app_id(app, args):
    return app.entry.id


def _op_confirm(app, args):
    text = host_module._text(args.get('text'))
    title = host_module._label(args.get('title')) or (app.entry.name or 'Elten')
    if app.ui is None:
        return False
    return bool(app._on_gui(lambda: app.ui.confirm(text, title), False))


def _op_select_action(app, args):
    entries = args.get('entries')
    if not isinstance(entries, list):
        return None
    rows = []
    for entry in entries[:host_module.MAX_ENTRIES]:
        if not isinstance(entry, dict):
            continue
        key = host_module._label(entry.get('key'))
        label = host_module._label(entry.get('label')) or key
        if key:
            rows.append((key, label))
    if not rows:
        return None
    header = host_module._label(args.get('header')) or (app.entry.name or '')
    start = host_module._label(args.get('start'))
    if app.ui is None:
        return None
    return app._on_gui(lambda: app.ui.select(rows, header, start), None)


def _op_select_item(app, args):
    items = args.get('items')
    if not isinstance(items, list):
        return None
    rows = [(str(index), host_module._label(value))
            for index, value in enumerate(items[:host_module.MAX_ENTRIES])]
    if not rows:
        return None
    header = host_module._label(args.get('header')) or (app.entry.name or '')
    if app.ui is None:
        return None
    chosen = app._on_gui(lambda: app.ui.select(rows, header, None), None)
    if chosen is None:
        return None
    try:
        return int(chosen)
    except (TypeError, ValueError):
        return None


def _op_choose_path(app, args):
    """A folder or a file, chosen with the platform's OWN picker.

    Not a tree of Titan's: somebody choosing where to save a download
    should get the dialog they already know, with their recent places in
    it, which their screen reader already reads.
    """
    if app.ui is None or not hasattr(app.ui, 'choose_path'):
        return None
    header = host_module._label(args.get('header'))
    start = str(args.get('path') or '')
    directory = bool(args.get('directory'))
    extensions = args.get('extensions')
    if not isinstance(extensions, list):
        extensions = []
    # A path an application suggests is a suggestion, not a place Titan
    # will go on its own: it is handed to a dialog the user answers.
    return app._on_gui(
        lambda: app.ui.choose_path(header, start, directory,
                                   [str(name) for name in extensions[:32]]),
        None)


def _op_open_keyboard(app, args):
    """Give an application a window that owns the keyboard.

    Asked for by `Runner#run` when nothing else is on the screen. Without
    it a game runs, ticks and receives not one key - which is not "a game
    with no keyboard", it is a game that never starts, makes no sound and
    looks broken.
    """
    if app.ui is None or not hasattr(app.ui, 'open_keyboard'):
        return False
    title = host_module._label(args.get('title')) or (app.entry.name or '')
    return bool(app._on_gui(
        lambda: app.ui.open_keyboard(app, title), False))


def _op_dirs(app, args):
    """The machine's own folders, in Elten's names.

    `eltendata` is Elten's own directory when Elten is installed, so an
    application that keeps something beside Elten's files finds it where it
    left it; without Elten it is the bridge's own, because the alternative
    is a path that is nowhere.
    """
    import tempfile
    from . import catalogue as catalogue_module
    home = os.path.expanduser('~')

    def known(*names):
        for name in names:
            candidate = os.path.join(home, name)
            if os.path.isdir(candidate):
                return candidate
        return home

    elten = catalogue_module.elten_root()
    return {
        'user': home,
        'appdata': os.environ.get('APPDATA', home),
        'documents': known('Documents', 'Dokumenty'),
        'desktop': known('Desktop', 'Pulpit'),
        'music': known('Music', 'Muzyka'),
        'tmp': tempfile.gettempdir(),
        'eltendata': elten or app.paths.root('data'),
        'apps': catalogue_module.elten_source_dir() or app.paths.root('asset'),
        'appsdata': catalogue_module.elten_data_dir() or app.paths.root('data'),
        'soundthemes': os.path.join(elten, 'soundthemes') if elten else '',
        'extras': os.path.join(elten, 'extras') if elten else '',
    }


def _op_display_text(app, args):
    """A page of text to read. With no window, it is spoken instead - which
    is what Elten itself would do with it."""
    text = host_module._text(args.get('text'))
    header = host_module._label(args.get('header')) or (app.entry.name or '')
    if app.ui is None or not hasattr(app.ui, 'display_text'):
        app.speaker.say(text)
        return None
    return app._on_gui(lambda: app.ui.display_text(text, header))


def _op_input_text(app, args):
    if app.ui is None:
        return None
    prompt = host_module._text(args.get('prompt'))
    default = host_module._text(args.get('default'))
    multiline = bool(args.get('multiline'))
    password = bool(args.get('password'))
    return app._on_gui(
        lambda: app.ui.input_text(prompt, default, multiline, password), None)


def _clean_control_spec(spec):
    """A control's description, sanitised the way any string reaching a
    widget must be - through `host_module`'s own limits, never trusted raw.
    """
    clean = {'kind': str(spec.get('kind') or '')}
    if 'label' in spec:
        clean['label'] = host_module._label(spec.get('label'))
    if 'header' in spec:
        clean['header'] = host_module._label(spec.get('header'))
    if 'text' in spec:
        clean['text'] = host_module._text(spec.get('text'))
    if 'checked' in spec:
        clean['checked'] = bool(spec.get('checked'))
    if 'multiline' in spec:
        clean['multiline'] = bool(spec.get('multiline'))
    if 'password' in spec:
        clean['password'] = bool(spec.get('password'))
    if 'readonly' in spec:
        clean['readonly'] = bool(spec.get('readonly'))
    if 'enabled' in spec:
        clean['enabled'] = bool(spec.get('enabled'))
    if 'max_length' in spec:
        try:
            clean['max_length'] = int(spec.get('max_length'))
        except (TypeError, ValueError):
            pass
    if 'options' in spec:
        options = spec.get('options')
        if isinstance(options, list):
            clean['options'] = [host_module._label(item)
                                for item in options[:host_module.MAX_ENTRIES]]
    if 'columns' in spec:
        columns = spec.get('columns')
        if isinstance(columns, list):
            clean['columns'] = [host_module._label(name)
                                for name in columns[:64]]
    if 'rows' in spec:
        rows = spec.get('rows')
        if isinstance(rows, list):
            clean['rows'] = [
                [host_module._label(cell) for cell in row[:64]]
                if isinstance(row, list) else [host_module._label(row)]
                for row in rows[:host_module.MAX_ENTRIES]]
    if 'header' in spec:
        clean['header'] = host_module._label(spec.get('header'))
    if 'empty_label' in spec:
        clean['empty_label'] = host_module._label(spec.get('empty_label'))
    if 'cells' in spec:
        cells = spec.get('cells')
        if isinstance(cells, list):
            clean['cells'] = [
                [host_module._label(cell) for cell in row[:256]]
                if isinstance(row, list) else [host_module._label(row)]
                for row in cells[:256]]
    for number in ('index', 'x', 'y', 'width', 'height'):
        if number in spec:
            try:
                clean[number] = int(spec.get(number))
            except (TypeError, ValueError):
                pass
    return clean


def _op_form_open(app, args):
    """Build one screen out of the controls an application named.

    An Elten application's own screen - `media_catalog`'s station list,
    `filemanager`'s file view, whatever an application not yet written asks
    for - is a `Form` of `ListBox`/`EditBox`/`Button`/`CheckBox`, and this is
    the one place they all arrive: `ui.py`'s `WxUI.open_form` is what turns
    the list of specs into real wx widgets. A headless run (`app.ui is
    None`, which is what the tests and an action-API call are) answers None
    rather than hanging, and the Ruby side treats that as "there is nowhere
    to show this" and returns at once.
    """
    if app.ui is None or not hasattr(app.ui, 'open_form'):
        return None
    specs = args.get('controls')
    if not isinstance(specs, list):
        specs = []
    clean = [_clean_control_spec(spec) if isinstance(spec, dict) else
            {'kind': ''} for spec in specs[:host_module.MAX_ENTRIES]]
    header = host_module._label(args.get('header'))
    cancel = args.get('cancel')
    accept = args.get('accept')
    return app._on_gui(
        lambda: app.ui.open_form(app, clean, cancel, accept, header), None)


def _op_form_close(app, args):
    if app.ui is None:
        return False
    form_id = host_module._handle(args.get('form'))
    return bool(app._on_gui(lambda: app.ui.close_form(form_id), False))


def _op_control_set(app, args):
    """An application changed a control it already put on screen -
    `list.options = [...]`, `box.text = "..."`, a button relabelled."""
    if app.ui is None:
        return False
    form_id = host_module._handle(args.get('form'))
    index = host_module._handle(args.get('control'))
    changes = {key: value for key, value in args.items()
              if key not in ('form', 'control')}
    changes = _clean_control_spec(changes)
    changes.pop('kind', None)
    return bool(app._on_gui(
        lambda: app.ui.set_control(form_id, index, changes), False))


def _op_elten_whoami(app, args):
    """Who the user is on EltenLink - the name only, never a token."""
    from . import eltenlink as eltenlink_module
    try:
        return eltenlink_module.whoami()
    except Exception:
        return ''


def _op_elten(app, args):
    """`EltenLink.<Namespace>.<method>` - the network, through Titan's own
    client and the user's own session.

    Never `getattr` on a name the application supplied: the namespace and
    method are looked up in a table, so an application reaches what is
    written down and nothing else.
    """
    from . import eltenlink as eltenlink_module
    namespace = str(args.get('namespace') or '')
    method = str(args.get('method') or '')
    arguments = args.get('args')
    if not isinstance(arguments, list):
        arguments = []
    if len(arguments) > 16:
        arguments = arguments[:16]
    try:
        return eltenlink_module.call(namespace, method, arguments)
    except eltenlink_module.EltenUnavailable as error:
        raise _Refused(str(error))


class _Refused(Exception):
    """Something Titan will not or cannot do, said in a sentence."""


def _op_task_begin(app, args):
    app._task_next += 1
    token = app._task_next
    app._tasks[token] = {'cancelled': False,
                         'title': host_module._label(args.get('title'))}
    return token


def _op_task_progress(app, args):
    token = host_module._handle(args.get('token'))
    task = app._tasks.get(token)
    if task is None:
        return False
    text = host_module._label(args.get('text'))
    if text and app.ui is not None:
        app._on_gui(lambda: app.ui.progress(text), None)
    return True


def _op_task_cancelled(app, args):
    task = app._tasks.get(host_module._handle(args.get('token')))
    return bool(task and task['cancelled'])


def _op_task_end(app, args):
    app._tasks.pop(host_module._handle(args.get('token')), None)
    return True


#: Calls: the application is blocked until each of these answers.
OPERATIONS = {
    'speak': _op_speak,
    'stop_speech': _op_stop_speech,
    'speaking': _op_speaking,
    'translate': _op_translate,
    'translate_plural': _op_translate_plural,
    'path': _op_path,
    'lock': _op_lock,
    'unlock': _op_unlock,
    'control_focus': _op_control_focus,
    'popup_menu': _op_popup_menu,
    'stream_open': _op_stream_open,
    'stream_do': _op_stream_do,
    'elten_whoami': _op_elten_whoami,
    'sound_asset': _op_sound_asset,
    'sound_create': _op_sound_create,
    'sound_play': _op_sound_play,
    'sound_stop': _op_sound_stop,
    'sound_playing': _op_sound_playing,
    'sound_volume': _op_sound_volume,
    'sound_position': _op_sound_position,
    'sound_pause': _op_sound_pause,
    'sound_close': _op_sound_close,
    'sound_pool_play': _op_sound_pool_play,
    'sound_pool_close': _op_sound_pool_close,
    'play_cue': _op_play_cue,
    'key_held': _op_key_held,
    'app_name': _op_app_name,
    'app_description': _op_app_description,
    'app_version': _op_app_version,
    'app_id': _op_app_id,
    'confirm': _op_confirm,
    'select_action': _op_select_action,
    'select_item': _op_select_item,
    'choose_path': _op_choose_path,
    'open_keyboard': _op_open_keyboard,
    'dirs': _op_dirs,
    'display_text': _op_display_text,
    'input_text': _op_input_text,
    'form_open': _op_form_open,
    'form_close': _op_form_close,
    'control_set': _op_control_set,
    'elten': _op_elten,
    'task_begin': _op_task_begin,
    'task_progress': _op_task_progress,
    'task_cancelled': _op_task_cancelled,
    'task_end': _op_task_end,
}


def _note_log(app, args):
    app._note(str(args.get('level') or 'info'),
              host_module._text(args.get('text')))


def _note_started(app, args):
    app.status = 'running'
    app.started.set()


def _note_ended(app, args):
    app.status = str(args.get('status') or 'finished')
    app.detail = host_module._text(args.get('detail'))
    app.ended.set()


def _note_runner_begin(app, args):
    keys = args.get('keys')
    app._watched = set(str(name) for name in keys) if isinstance(keys, list) \
        else set()


def _note_runner_end(app, args):
    app._watched = set()


#: Notifications: nothing is waiting, so these must not answer.
NOTIFICATIONS = {
    'log': _note_log,
    'started': _note_started,
    'ended': _note_ended,
    'runner_begin': _note_runner_begin,
    'runner_end': _note_runner_end,
}
