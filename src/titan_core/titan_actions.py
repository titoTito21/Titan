"""Join the Titan Action Bus - the one call an add-on makes to become
controllable by Titan's AI agent and voice assistant.

    from src.titan_core.titan_actions import serve

    serve({
        'open_file': lambda path: editor.open(path),
        'save':      lambda: editor.save(),
    }, id='tedit', label='Text Editor')

That is the whole integration. ``serve`` returns immediately; a daemon thread
keeps the connection to Titan and answers invocations for as long as the
application runs. If Titan is not running, or is restarted, the thread keeps
trying quietly in the background - joining the bus never blocks or breaks the
application.

**Only the standard library is imported here**, and nothing is imported from
``src`` at module level. An add-on may be a wxPython app, a Tk launcher, a
console script or a game loop, and none of those can be assumed to have
pywin32, wx, or a Titan install on the path.

Thread safety: handlers are called on the bus thread by default, which is wrong
for anything that touches a GUI. If wxPython or Tk is in play the call is
marshalled onto the interface thread automatically; pass ``marshal=`` to do it
yourself.
"""

import inspect
import json
import os
import sys
import threading
import time

PIPE_NAME = r'\\.\pipe\TitanActions'
TOKEN_FILENAME = 'bus.token'

_RECONNECT_DELAY = 5.0
_UI_TIMEOUT = 30.0

_worker = None
_stop = threading.Event()
_state = {'connected': False, 'last_error': ''}


def _log(message):
    print(f"[titan_actions] {message}")


# --------------------------------------------------------------------------- #
# Token (computed the same way Titan computes it, so nothing has to be passed)
# --------------------------------------------------------------------------- #
def _token_path():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'titosoft', 'Titan', 'actions', TOKEN_FILENAME)


def _read_token():
    try:
        with open(_token_path(), 'r', encoding='utf-8') as handle:
            return handle.read().strip()
    except Exception:
        return ''


# --------------------------------------------------------------------------- #
# The pipe channel, shared by both ends of the bus
# --------------------------------------------------------------------------- #
# Titan's own side (src/titan_core/actions/bus.py) imports PipeChannel from
# here rather than keeping a second copy: there must be exactly one definition
# of the wire behaviour. The dependency only ever points this way - this module
# imports nothing from Titan, so an add-on can vendor it or import it directly
# without dragging a Titan install along.
#
# The handles are OVERLAPPED, and that is not a detail. A synchronous pipe
# handle serialises every operation on the file object, so a thread parked in
# ReadFile waiting for the next request blocks the thread trying to WriteFile a
# response - which is exactly the shape of this protocol, and shows up as the
# connection collapsing on the first call. Each direction therefore gets its
# own OVERLAPPED and its own event, which is the supported way to have a read
# and a write in flight at the same time.

FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997
ERROR_PIPE_CONNECTED = 535
ERROR_PIPE_BUSY = 231
INFINITE = 0xFFFFFFFF
MAX_LINE = 4 * 1024 * 1024


def _overlapped_type():
    import ctypes
    from ctypes import wintypes

    class OVERLAPPED(ctypes.Structure):
        _fields_ = [('Internal', ctypes.c_void_p),
                    ('InternalHigh', ctypes.c_void_p),
                    ('Offset', wintypes.DWORD),
                    ('OffsetHigh', wintypes.DWORD),
                    ('hEvent', wintypes.HANDLE)]

    return OVERLAPPED


class PipeChannel:
    """Newline-delimited JSON over one overlapped Windows pipe handle.

    Safe for one reader thread and one writer thread at once, which is what a
    push protocol needs.
    """

    def __init__(self, handle):
        import ctypes
        from ctypes import wintypes
        self._ctypes = ctypes
        self._wintypes = wintypes
        self._kernel32 = ctypes.windll.kernel32
        self.handle = handle
        self._buffer = b''
        self._closed = False
        self._write_lock = threading.Lock()
        self._overlapped = _overlapped_type()

        create_event = self._kernel32.CreateEventW
        create_event.restype = wintypes.HANDLE
        create_event.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                                 wintypes.LPCWSTR]
        # Manual-reset events, one per direction.
        self._read_event = create_event(None, True, False, None)
        self._write_event = create_event(None, True, False, None)

        self._read_file = self._kernel32.ReadFile
        self._read_file.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                    wintypes.DWORD,
                                    ctypes.POINTER(wintypes.DWORD),
                                    ctypes.c_void_p]
        self._read_file.restype = wintypes.BOOL
        self._write_file = self._kernel32.WriteFile
        self._write_file.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                     wintypes.DWORD,
                                     ctypes.POINTER(wintypes.DWORD),
                                     ctypes.c_void_p]
        self._write_file.restype = wintypes.BOOL
        self._result = self._kernel32.GetOverlappedResult
        self._result.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                 ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
        self._result.restype = wintypes.BOOL

    # ----------------------------------------------------------------- opening
    @classmethod
    def connect(cls, name, attempts=3):
        """Open the client end of ``name``, or return None."""
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        invalid = wintypes.HANDLE(-1).value

        create = kernel32.CreateFileW
        create.restype = wintypes.HANDLE
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                           wintypes.HANDLE]
        for _ in range(max(1, attempts)):
            handle = create(name, GENERIC_READ | GENERIC_WRITE, 0, None,
                            OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
            if handle and handle != invalid:
                return cls(handle)
            if kernel32.GetLastError() != ERROR_PIPE_BUSY:
                return None
            kernel32.WaitNamedPipeW(name, 2000)
        return None

    # --------------------------------------------------------------------- I/O
    def _finish(self, overlapped, event, count):
        """Complete an operation that came back ERROR_IO_PENDING."""
        ctypes = self._ctypes
        if self._kernel32.GetLastError() != ERROR_IO_PENDING:
            return False
        self._kernel32.WaitForSingleObject(event, INFINITE)
        return bool(self._result(self.handle, ctypes.byref(overlapped),
                                 ctypes.byref(count), True))

    def read_line(self):
        """Block until a whole line arrives. None means the peer went away."""
        ctypes, wintypes = self._ctypes, self._wintypes
        chunk = (ctypes.c_ubyte * 8192)()
        while True:
            index = self._buffer.find(b'\n')
            if index >= 0:
                line, self._buffer = self._buffer[:index], self._buffer[index + 1:]
                return line
            if len(self._buffer) > MAX_LINE or self._closed:
                return None
            overlapped = self._overlapped()
            overlapped.hEvent = self._read_event
            self._kernel32.ResetEvent(self._read_event)
            got = wintypes.DWORD(0)
            ok = self._read_file(self.handle, ctypes.byref(chunk), 8192,
                                 ctypes.byref(got), ctypes.byref(overlapped))
            if not ok and not self._finish(overlapped, self._read_event, got):
                return None
            if got.value == 0:
                return None
            self._buffer += bytes(chunk[:got.value])

    def write_line(self, obj):
        ctypes, wintypes = self._ctypes, self._wintypes
        try:
            data = (json.dumps(obj, ensure_ascii=False) + '\n').encode('utf-8')
        except Exception:
            return False
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        with self._write_lock:
            if self._closed:
                return False
            written = 0
            while written < len(data):
                overlapped = self._overlapped()
                overlapped.hEvent = self._write_event
                self._kernel32.ResetEvent(self._write_event)
                count = wintypes.DWORD(0)
                ok = self._write_file(self.handle, ctypes.byref(buf, written),
                                      len(data) - written, ctypes.byref(count),
                                      ctypes.byref(overlapped))
                if not ok and not self._finish(overlapped, self._write_event,
                                               count):
                    return False
                if count.value == 0:
                    return False
                written += count.value
        return True

    def close(self):
        with self._write_lock:
            if self._closed:
                return
            self._closed = True
            handle, self.handle = self.handle, None
        if handle:
            try:
                self._kernel32.CancelIoEx(handle, None)
            except Exception:
                pass
            try:
                self._kernel32.CloseHandle(handle)
            except Exception:
                pass
        for event in (self._read_event, self._write_event):
            try:
                self._kernel32.CloseHandle(event)
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Calling the add-on's own code safely
# --------------------------------------------------------------------------- #
def _wx_marshal():
    """A marshaller onto the wx main thread, or None when wx is not running."""
    wx = sys.modules.get('wx')
    if wx is None:
        return None
    try:
        if wx.GetApp() is None:
            return None
    except Exception:
        return None

    def run(func):
        box = {}
        done = threading.Event()

        def call():
            try:
                box['value'] = func()
            except Exception as e:               # noqa: BLE001 - relayed below
                box['error'] = e
            finally:
                done.set()

        wx.CallAfter(call)
        if not done.wait(_UI_TIMEOUT):
            raise TimeoutError("the application's interface did not respond")
        if 'error' in box:
            raise box['error']
        return box.get('value')

    return run


def needs(name, prompt, options=None, kind='string', default=''):
    """Say that this action needs ``name`` before it can run.

        def copy_photos(destination=''):
            if not destination:
                return needs('destination', "Where should I copy them?",
                             options=['the USB stick', 'Documents'])

    Asking is an outcome, not a failure: Titan hands the question to whoever
    asked - the AI puts it to the user and calls again with the answer, a
    component shows a dialog - and the action runs once, with a real answer,
    instead of running now on a guess.

    Defined here as well as in ``src.titan_core.actions`` so an add-on that
    keeps no Titan import at all can still ask.
    """
    return {'__titan_question__': True,
            'question': {'name': str(name or 'answer'),
                         'prompt': str(prompt or ''),
                         'options': [str(o) for o in (options or [])],
                         'kind': kind,
                         'default': default}}


def fails(reason):
    """Say that this action could not do what was asked.

        if not os.path.isfile(path):
            return fails(f"There is no file at {path}.")

    Prose alone is not enough: a caller chaining several actions cannot tell
    "there is no such note" from success, and carries on to the step that
    assumed otherwise. The reason is what the user is told, so write it for
    them.
    """
    return {'__titan_failed__': True,
            'reason': str(reason or 'the action did not succeed')}


def _encode_result(value):
    """Make a handler's return value safe to put on the wire.

    A handler may return a Question or Failure object (imported from Titan)
    rather than the plain dicts ``needs()`` and ``fails()`` build. Left alone
    those would fail to serialise and take the connection down with them, so
    they are converted here.
    """
    to_dict = getattr(value, 'to_dict', None)
    if callable(to_dict) and hasattr(value, 'prompt'):
        try:
            return {'__titan_question__': True, 'question': to_dict()}
        except Exception:
            return str(value)
    if hasattr(value, 'reason') and callable(to_dict):
        return {'__titan_failed__': True, 'reason': str(value.reason)}
    if isinstance(value, (str, int, float, bool, list, dict)) or value is None:
        return value
    return str(value)


def _call_handler(handler, args, marshal):
    """Call a handler with only the arguments it actually declares, on the
    right thread."""
    kwargs = dict(args or {})
    try:
        signature = inspect.signature(handler)
        accepts_any = any(p.kind is inspect.Parameter.VAR_KEYWORD
                          for p in signature.parameters.values())
        if not accepts_any:
            allowed = {name for name, p in signature.parameters.items()
                       if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                     inspect.Parameter.KEYWORD_ONLY)}
            kwargs = {k: v for k, v in kwargs.items() if k in allowed}
    except (TypeError, ValueError):
        pass

    runner = marshal or _wx_marshal()
    if runner is not None:
        return runner(lambda: handler(**kwargs))
    return handler(**kwargs)


def _describe(handlers, declared):
    """What this add-on tells Titan it can do. An explicit ``actions`` list
    wins; otherwise the handler names and their parameters are used, which is
    enough for Titan to build a working tool."""
    if declared:
        return declared
    described = []
    for name, handler in handlers.items():
        params = {}
        try:
            for pname, parameter in inspect.signature(handler).parameters.items():
                if parameter.kind in (inspect.Parameter.VAR_KEYWORD,
                                      inspect.Parameter.VAR_POSITIONAL):
                    continue
                params[pname] = {
                    'type': 'string',
                    'required': parameter.default is inspect.Parameter.empty,
                }
        except (TypeError, ValueError):
            pass
        summary = (inspect.getdoc(handler) or '').strip().split('\n')[0]
        described.append({'name': name, 'summary': summary, 'params': params})
    return described


# --------------------------------------------------------------------------- #
# Calling the other way: this add-on asking Titan to run somebody else's action
# --------------------------------------------------------------------------- #
# The bus is deliberately bidirectional. A component calling another component
# can just import src.titan_core.actions, because both are inside Titan. An
# application cannot: it is a separate process, so its "registry" would be a
# second, blind copy that cannot see Titan's loaded components or the other
# applications on the bus. Asking Titan over the connection that is already
# open is the only answer that is actually correct.

_call_lock = threading.Lock()
_outbound = {'channel': None, 'next_id': 1}
_pending_calls = {}


class Result:
    """The outcome of calling somebody else's action. Truthy when it worked.

    ``question`` is set when the action asked for something instead of running
    - a dict with ``name``, ``prompt`` and ``options``. Ask the user, then call
    again with that name among the arguments.
    """

    def __init__(self, ok, text, question=None):
        self.ok = bool(ok)
        self.text = text or ''
        self.question = question

    @property
    def pending(self):
        return self.question is not None

    def __bool__(self):
        return self.ok

    def __str__(self):
        return self.text

    def __repr__(self):
        return f"<Result ok={self.ok} {self.text[:60]!r}>"


def _resolve_call(message):
    with _call_lock:
        waiter = _pending_calls.pop(message.get('id'), None)
    if waiter is not None:
        waiter[1] = message
        waiter[0].set()


def _fail_pending_calls(reason):
    with _call_lock:
        waiters = list(_pending_calls.values())
        _pending_calls.clear()
    for waiter in waiters:
        waiter[1] = {'ok': False, 'error': reason}
        waiter[0].set()


def _ask_titan(payload, timeout):
    with _call_lock:
        channel = _outbound['channel']
        if channel is None:
            return {'ok': False, 'error': 'Titan is not connected'}
        request_id = _outbound['next_id']
        _outbound['next_id'] += 1
        waiter = [threading.Event(), None]
        _pending_calls[request_id] = waiter
    payload['id'] = request_id
    if not channel.write_line(payload):
        with _call_lock:
            _pending_calls.pop(request_id, None)
        return {'ok': False, 'error': 'could not reach Titan'}
    if not waiter[0].wait(timeout):
        with _call_lock:
            _pending_calls.pop(request_id, None)
        return {'ok': False, 'error': f'Titan did not answer within {int(timeout)}s'}
    return waiter[1] or {'ok': False, 'error': 'no answer'}


def call(addon, action, timeout=30.0, **args):
    """Ask Titan to run another add-on's action, and wait for the answer.

        from src.titan_core.titan_actions import call

        result = call('tmedia', 'play', query='the news')
        if result:
            print(result.text)

    Works from any add-on that has called ``serve()``: components, widgets,
    other applications, anything the user has installed. Never raises.
    """
    if not _state['connected']:
        return Result(False, "Titan is not connected, so nothing else can be "
                             "called right now.")
    answer = _ask_titan({'type': 'call', 'addon': addon, 'action': action,
                         'args': args}, timeout)
    if not answer.get('ok'):
        return Result(False, str(answer.get('error') or 'the call failed'),
                      question=answer.get('question'))
    return Result(True, str(answer.get('result') or ''))


def call_sequence(steps, stop_on_error=True, timeout=120.0):
    """Ask Titan to run several actions in order, as one composite command.

        call_sequence([
            {'addon': 'tnotes', 'action': 'read_note', 'args': {'title': 'x'}},
            {'addon': 'tweb', 'action': 'open_url', 'args': {'url': '{{1}}'}},
        ])

    ``{{1}}`` is what step 1 returned. The run stops at the first step that
    fails or asks a question, and ``result.text`` names every step either way.
    """
    if not _state['connected']:
        return Result(False, "Titan is not connected.")
    answer = _ask_titan({'type': 'sequence', 'steps': list(steps or []),
                         'stop_on_error': bool(stop_on_error)}, timeout)
    if not answer.get('ok'):
        return Result(False, str(answer.get('error') or 'the sequence failed'),
                      question=answer.get('question'))
    return Result(True, str(answer.get('result') or ''))


def list_addons(timeout=15.0):
    """What else is installed and can be called. A list of dicts with ``id``,
    ``label``, ``kind`` and ``actions``; empty when Titan is not connected."""
    if not _state['connected']:
        return []
    answer = _ask_titan({'type': 'list'}, timeout)
    if not answer.get('ok'):
        return []
    addons = answer.get('addons')
    return addons if isinstance(addons, list) else []


# --------------------------------------------------------------------------- #
# The bus thread
# --------------------------------------------------------------------------- #
def _serve_invoke(client, handlers, marshal, message):
    """Answer one invocation. Runs on its own thread, which matters twice over:
    a slow handler must not stall the session, and a handler that calls back
    into Titan (``call()`` below) needs the reader loop free to deliver its
    answer - doing this inline would deadlock."""
    request_id = message.get('id')
    name = message.get('action', '')
    handler = handlers.get(name)
    if handler is None:
        client.write_line({'type': 'result', 'id': request_id, 'ok': False,
                           'error': f"unknown action '{name}'"})
        return
    try:
        value = _encode_result(_call_handler(handler, message.get('args'),
                                             marshal))
        client.write_line({'type': 'result', 'id': request_id, 'ok': True,
                           'result': value})
    except Exception as e:
        client.write_line({'type': 'result', 'id': request_id, 'ok': False,
                           'error': f"{type(e).__name__}: {e}"})


def _session(client, handlers, hello, marshal):
    if not client.write_line(hello):
        return
    line = client.read_line()
    if line is None:
        return
    try:
        welcome = json.loads(line.decode('utf-8', errors='replace'))
    except Exception:
        return
    if not welcome.get('ok'):
        _state['last_error'] = str(welcome.get('error') or 'refused')
        _log(f"Titan refused the join: {_state['last_error']}")
        return
    _state['connected'] = True
    _state['last_error'] = ''
    with _call_lock:
        _outbound['channel'] = client
    _log(f"joined the Titan Action Bus as '{hello['id']}'")

    try:
        while not _stop.is_set():
            line = client.read_line()
            if line is None:
                break
            try:
                message = json.loads(line.decode('utf-8', errors='replace'))
            except Exception:
                continue
            kind = message.get('type')
            if kind == 'invoke':
                threading.Thread(
                    target=_serve_invoke,
                    args=(client, handlers, marshal, message),
                    name='TitanActionHandler', daemon=True).start()
            elif kind in ('call_result', 'list_result'):
                _resolve_call(message)
            elif kind == 'ping':
                client.write_line({'type': 'pong'})
    finally:
        with _call_lock:
            if _outbound['channel'] is client:
                _outbound['channel'] = None
        _fail_pending_calls("the connection to Titan was lost")
        _state['connected'] = False


def _worker_loop(handlers, hello, marshal):
    while not _stop.is_set():
        client = None
        try:
            client = PipeChannel.connect(PIPE_NAME)
            if client is not None:
                _session(client, handlers, hello, marshal)
            else:
                _state['last_error'] = 'Titan is not listening'
        except Exception as e:
            _state['last_error'] = str(e)
        finally:
            _state['connected'] = False
            if client is not None:
                client.close()
        # Titan may not be running yet, or may have been restarted. Keep
        # trying: an application often outlives one Titan session.
        _stop.wait(_RECONNECT_DELAY)


# --------------------------------------------------------------------------- #
# Public surface
# --------------------------------------------------------------------------- #
def serve(handlers, id=None, label='', kind='app', actions=None, marshal=None):
    """Offer ``handlers`` to Titan's AI for as long as this process runs.

    Args:
        handlers: {action name -> callable}. The callable is invoked with the
            named arguments Titan sends; parameters it does not declare are
            dropped, so adding a parameter later never breaks an old handler.
            Return a string to tell the AI what happened; anything else is
            serialised as JSON.
        id: Stable add-on id, matching ``__actions.json``. Defaults to the
            name of the directory the running script lives in.
        label: Human name, used when the AI talks about this add-on.
        kind: 'app', 'game', or any other Titan add-on kind.
        actions: Optional richer declaration (summaries, types, risk levels) in
            the same shape as the ``actions`` array of ``__actions.json``. When
            omitted it is derived from the handlers themselves.
        marshal: Optional callable(func) -> result that runs ``func`` on the
            interface thread. wxPython is detected automatically; a Tk add-on
            should pass one built on ``root.after``.

    Returns True when the bus thread was started (it is started even if Titan
    is not running yet - it connects as soon as Titan appears).
    """
    global _worker
    if sys.platform != 'win32':
        return False
    if _worker is not None and _worker.is_alive():
        return True
    if not isinstance(handlers, dict) or not handlers:
        _log("serve() needs a non-empty {name: callable} mapping")
        return False

    if not id:
        try:
            main = sys.modules.get('__main__')
            script = getattr(main, '__file__', '') or sys.argv[0]
            id = os.path.basename(os.path.dirname(os.path.abspath(script)))
        except Exception:
            id = 'addon'
    id = ''.join(ch if ch.isalnum() or ch == '_' else '_'
                 for ch in str(id).lower()).strip('_') or 'addon'

    hello = {
        'type': 'hello',
        'token': _read_token(),
        'id': id,
        'label': label or id,
        'kind': kind,
        'pid': os.getpid(),
        'path': os.path.abspath(os.path.dirname(sys.argv[0] or '.')),
        'actions': _describe(handlers, actions),
    }

    _stop.clear()
    _worker = threading.Thread(target=_worker_loop,
                               args=(dict(handlers), hello, marshal),
                               name='TitanActionBusClient', daemon=True)
    _worker.start()
    return True


def connect(id=None, label='', kind='app'):
    """Join the bus purely as a caller, offering nothing.

    ``serve()`` is for an add-on that wants to be driven. An add-on that only
    wants to *use* other add-ons - open a file in the editor, show a page in
    the browser, hand a download to the download manager - calls this instead,
    and then ``call()`` and ``list_addons()`` work exactly the same way.

        from src.titan_core.titan_actions import connect, call

        connect(id='myapp', label='My App')
        call('tweb', 'open_url', url='https://example.org')

    Returns True when the bus thread was started.
    """
    def _alive():
        """A no-op action, so the add-on still shows up as running."""
        return "Running."

    return serve({'__alive__': _alive}, id=id, label=label, kind=kind,
                 actions=[])


def stop():
    """Leave the bus. Rarely needed - the thread is a daemon."""
    _stop.set()


def is_connected():
    """True while Titan is on the other end."""
    return bool(_state['connected'])


def tk_marshal(root):
    """Build a ``marshal`` for a Tk add-on: handlers then run on the Tk thread.

        serve(HANDLERS, marshal=tk_marshal(root))
    """
    def run(func):
        box = {}
        done = threading.Event()

        def call():
            try:
                box['value'] = func()
            except Exception as e:               # noqa: BLE001 - relayed below
                box['error'] = e
            finally:
                done.set()

        root.after(0, call)
        if not done.wait(_UI_TIMEOUT):
            raise TimeoutError("the application's interface did not respond")
        if 'error' in box:
            raise box['error']
        return box.get('value')

    return run


def run_cli(handlers, argv=None):
    """Serve ONE action from the command line and exit - the headless half of
    the contract.

    Titan runs an add-on's action module like this when the add-on is not
    running (or when the action does not need it to be)::

        python tedit_actions.py open_file "{\\"path\\": \\"C:/notes.txt\\"}"

    so the same handler table answers both transports::

        HANDLERS = {'open_file': open_file, 'save': save}

        if __name__ == '__main__':
            from src.titan_core.titan_actions import run_cli
            run_cli(HANDLERS)
        else:
            from src.titan_core.titan_actions import serve
            serve(HANDLERS, id='tedit')

    The result is printed to stdout as one JSON object, which is the only thing
    Titan reads - anything the handler prints itself is ignored.
    """
    argv = list(argv if argv is not None else sys.argv[1:])
    name = argv[0] if argv else ''
    args = {}
    if len(argv) > 1 and argv[1].strip():
        try:
            parsed = json.loads(argv[1])
            if isinstance(parsed, dict):
                args = parsed
        except Exception as e:
            print(json.dumps({'ok': False, 'error': f'bad arguments: {e}'}))
            return 2

    handler = handlers.get(name)
    if handler is None:
        print(json.dumps({'ok': False,
                          'error': f"unknown action '{name}'",
                          'available': sorted(handlers)}))
        return 2
    try:
        value = _encode_result(_call_handler(handler, args, None))
        print(json.dumps({'ok': True, 'result': value}, ensure_ascii=False,
                         default=str))
        return 0
    except Exception as e:
        print(json.dumps({'ok': False, 'error': f'{type(e).__name__}: {e}'},
                         ensure_ascii=False))
        return 1


def wait_until_connected(timeout=10.0):
    """Block until Titan answers. Only useful in a script that wants to know."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _state['connected']:
            return True
        time.sleep(0.2)
    return False
