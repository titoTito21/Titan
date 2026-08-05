"""The Action Bus - how Titan reaches an application that is already running.

Applications and games are separate processes, so a headless action (a
short-lived subprocess that prints JSON) cannot answer "save the document I
have open" or "what is playing right now". The bus is what can.

Titan hosts one named pipe, ``\\\\.\\pipe\\TitanActions``. An application opts
in with a single call to ``src.titan_core.titan_actions.serve()``; that library
connects back, announces itself, and then serves invocations for as long as it
runs. Titan therefore knows every live instance - including ones the user
started outside Titan - without scanning anything.

Wire format: UTF-8, newline-delimited JSON, one object per line.

    app -> Titan   {"type":"hello","token":"...","id":"tedit","label":"Text
                    Editor","kind":"app","pid":4812,"actions":[...]}
    Titan -> app   {"type":"invoke","id":7,"action":"open_file",
                    "args":{"path":"C:/notes.txt"}}
    app -> Titan   {"type":"result","id":7,"ok":true,"result":"Opened notes.txt"}
    app -> Titan   {"type":"event","name":"...","data":{...}}   (optional)

The pipe is machine-wide, as all named pipes are, so a hello carrying the wrong
token is dropped: the token file lives in the user's own profile and only
processes that can read it can join the bus.

Only ctypes and the standard library are used on both sides. The client library
must import cleanly into a wx app, a Tk launcher or a console script, none of
which can be assumed to have pywin32.
"""

import json
import os
import sys
import threading
import time

PIPE_NAME = r'\\.\pipe\TitanActions'
TOKEN_FILENAME = 'bus.token'
PROTOCOL_VERSION = 1

_MAX_LINE = 4 * 1024 * 1024      # a result may carry a document; still bounded
_DEFAULT_TIMEOUT = 20.0

_server_thread = None
_server_stop = threading.Event()
_peers = {}                      # addon_id -> _Peer
_peers_lock = threading.RLock()


def _log(message):
    print(f"[action_bus] {message}")


# --------------------------------------------------------------------------- #
# Token
# --------------------------------------------------------------------------- #
def token_path():
    """Where the shared secret lives. Same computation in Titan and in the
    client library, so neither has to tell the other."""
    try:
        from src import platform_utils
        base = platform_utils.ensure_user_data_subdir('actions')
    except Exception:
        base = os.path.join(
            os.environ.get('APPDATA') or os.path.expanduser('~'),
            'titosoft', 'Titan', 'actions')
        os.makedirs(base, exist_ok=True)
    return os.path.join(base, TOKEN_FILENAME)


def read_token():
    try:
        with open(token_path(), 'r', encoding='utf-8') as handle:
            return handle.read().strip()
    except Exception:
        return ''


def ensure_token():
    """The token is created once and kept: an application that was running
    before Titan restarted must still be able to rejoin."""
    existing = read_token()
    if existing:
        return existing
    import secrets
    token = secrets.token_hex(24)
    try:
        with open(token_path(), 'w', encoding='utf-8') as handle:
            handle.write(token)
    except Exception as e:
        _log(f"could not store the bus token: {e}")
        return ''
    return token


# --------------------------------------------------------------------------- #
# One connected application
# --------------------------------------------------------------------------- #
class _Peer:
    """A running add-on process that has joined the bus."""

    def __init__(self, handle, io, hello):
        self.handle = handle
        self.io = io
        self.addon_id = hello.get('id') or 'addon'
        self.label = hello.get('label') or self.addon_id
        self.kind = hello.get('kind') or 'app'
        self.pid = hello.get('pid') or 0
        self.actions = hello.get('actions') or []
        self.path = hello.get('path') or ''
        self.joined_at = time.time()
        self.alive = True

        self._next_id = 1
        self._pending = {}         # request id -> [event, response]
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- calling
    def invoke(self, action, args, timeout=_DEFAULT_TIMEOUT):
        """Run one action in the peer process. Returns (ok, result)."""
        if not self.alive:
            return False, "the application is no longer connected"
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            waiter = [threading.Event(), None]
            self._pending[request_id] = waiter
        payload = {'type': 'invoke', 'id': request_id, 'action': action,
                   'args': args or {}}
        if not self.io.write_line(payload):
            with self._lock:
                self._pending.pop(request_id, None)
            self.close()
            return False, "the connection to the application was lost"
        if not waiter[0].wait(timeout):
            with self._lock:
                self._pending.pop(request_id, None)
            return False, (f"the application did not answer within "
                           f"{int(timeout)} seconds")
        response = waiter[1] or {}
        if not response.get('ok', False):
            return False, str(response.get('error') or "the action failed")
        result = response.get('result')
        if result is None:
            result = f"Done ({action})."
        elif isinstance(result, dict) and (result.get('__titan_question__')
                                           or result.get('__titan_failed__')):
            # A question or a stated failure, not an answer: the dispatcher
            # turns it into the right kind of result, so it must arrive
            # unflattened.
            return True, result
        elif not isinstance(result, str):
            try:
                result = json.dumps(result, ensure_ascii=False)
            except Exception:
                result = str(result)
        return True, result

    def _resolve(self, message):
        request_id = message.get('id')
        with self._lock:
            waiter = self._pending.pop(request_id, None)
        if waiter is not None:
            waiter[1] = message
            waiter[0].set()

    def close(self):
        if not self.alive:
            return
        self.alive = False
        self.io.close()
        with self._lock:
            waiters = list(self._pending.values())
            self._pending.clear()
        for waiter in waiters:
            waiter[1] = {'ok': False, 'error': "the application disconnected"}
            waiter[0].set()
        with _peers_lock:
            if _peers.get(self.addon_id) is self:
                del _peers[self.addon_id]


# --------------------------------------------------------------------------- #
# Named-pipe plumbing
# --------------------------------------------------------------------------- #
# The wire behaviour lives in src/titan_core/titan_actions.py, the module
# add-ons import, so there is exactly one definition of it and the two ends can
# never drift apart. That module deliberately imports nothing from Titan, which
# is why the dependency points this way round.
from src.titan_core.titan_actions import (      # noqa: E402
    PipeChannel, FILE_FLAG_OVERLAPPED, ERROR_PIPE_CONNECTED, INFINITE,
    _overlapped_type,
)


def _serve_request(peer, message):
    """An add-on asking Titan to reach another add-on.

    This is what makes a component able to drive a widget, an application able
    to drive a component, and so on. The dispatcher is imported here rather
    than at module scope because it imports this module back.
    """
    request_id = message.get('id')
    try:
        from src.titan_core.actions import dispatch
        kind = message.get('type')
        if kind == 'list':
            peer.io.write_line({'type': 'list_result', 'id': request_id,
                                'ok': True, 'addons': dispatch.list_addons()})
            return
        if kind == 'sequence':
            from src.titan_core.actions.sequence import run_sequence
            outcome = run_sequence(message.get('steps') or [],
                                   stop_on_error=message.get('stop_on_error',
                                                             True))
            payload = {'type': 'call_result', 'id': request_id,
                       'ok': outcome.ok, 'result': outcome.text,
                       'error': '' if outcome.ok else outcome.text}
            if outcome.pending and outcome.question is not None:
                payload['question'] = outcome.question.to_dict()
            peer.io.write_line(payload)
            return
        result = dispatch.run(message.get('addon') or '',
                              message.get('action') or '',
                              **(message.get('args') or {}))
        payload = {'type': 'call_result', 'id': request_id, 'ok': result.ok,
                   'result': result.text,
                   'error': '' if result.ok else result.text}
        # A pending result is not a failure: the caller gets the question so it
        # can ask its own user and try again.
        if result.pending and result.question is not None:
            payload['question'] = result.question.to_dict()
        peer.io.write_line(payload)
    except Exception as e:
        peer.io.write_line({'type': 'call_result', 'id': request_id,
                            'ok': False, 'error': f'{type(e).__name__}: {e}'})


def _serve_connection(handle):
    """Own one connected application until it disconnects."""
    io = PipeChannel(handle)
    peer = None
    try:
        line = io.read_line()
        if line is None:
            io.close()
            return
        try:
            hello = json.loads(line.decode('utf-8', errors='replace'))
        except Exception:
            io.close()
            return
        if hello.get('type') != 'hello':
            io.close()
            return
        expected = read_token()
        if expected and hello.get('token') != expected:
            _log(f"rejected a join with a bad token from pid {hello.get('pid')}")
            io.write_line({'type': 'welcome', 'ok': False,
                           'error': 'bad token'})
            io.close()
            return

        peer = _Peer(handle, io, hello)
        with _peers_lock:
            previous = _peers.get(peer.addon_id)
            if previous is not None and previous is not peer:
                previous.close()
            _peers[peer.addon_id] = peer
        io.write_line({'type': 'welcome', 'ok': True,
                       'version': PROTOCOL_VERSION})
        _log(f"'{peer.addon_id}' joined (pid {peer.pid}, "
             f"{len(peer.actions)} actions)")

        while True:
            line = io.read_line()
            if line is None:
                break
            try:
                message = json.loads(line.decode('utf-8', errors='replace'))
            except Exception:
                continue
            kind = message.get('type')
            if kind == 'result':
                peer._resolve(message)
            elif kind in ('call', 'list'):
                # The add-on is asking Titan to reach somebody else. Answered
                # on its own thread: dispatching here would block this peer's
                # reader, and the add-on it is calling may well be this same
                # peer, which would then never be able to answer.
                threading.Thread(target=_serve_request, args=(peer, message),
                                 name='TitanActionBusCall', daemon=True).start()
            elif kind == 'actions':
                # An add-on may re-declare its actions while it runs (a plugin
                # loaded, a document opened).
                if isinstance(message.get('actions'), list):
                    peer.actions = message['actions']
            elif kind == 'ping':
                io.write_line({'type': 'pong'})
            elif kind == 'bye':
                break
    except Exception as e:
        _log(f"connection error: {e}")
    finally:
        if peer is not None:
            _log(f"'{peer.addon_id}' left")
            peer.close()
        else:
            io.close()


def _accept_loop():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    PIPE_ACCESS_DUPLEX = 0x00000003
    PIPE_TYPE_BYTE = 0x00000000
    PIPE_READMODE_BYTE = 0x00000000
    PIPE_WAIT = 0x00000000
    PIPE_UNLIMITED_INSTANCES = 255
    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
    WAIT_OBJECT_0 = 0
    WAIT_TIMEOUT = 258

    create = kernel32.CreateNamedPipeW
    create.restype = wintypes.HANDLE
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                       wintypes.DWORD, ctypes.c_void_p]
    connect = kernel32.ConnectNamedPipe
    connect.restype = wintypes.BOOL
    connect.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    create_event = kernel32.CreateEventW
    create_event.restype = wintypes.HANDLE
    create_event.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL,
                             wintypes.LPCWSTR]

    overlapped_type = _overlapped_type()
    accept_event = create_event(None, True, False, None)

    _log("listening on " + PIPE_NAME)
    while not _server_stop.is_set():
        handle = create(PIPE_NAME, PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED,
                        PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                        PIPE_UNLIMITED_INSTANCES, 65536, 65536, 0, None)
        if not handle or handle == INVALID_HANDLE_VALUE:
            _log(f"CreateNamedPipeW failed: {kernel32.GetLastError()}")
            _server_stop.wait(2.0)
            continue

        overlapped = overlapped_type()
        overlapped.hEvent = accept_event
        kernel32.ResetEvent(accept_event)
        connected = bool(connect(handle, ctypes.byref(overlapped)))
        if not connected:
            error = kernel32.GetLastError()
            if error == ERROR_PIPE_CONNECTED:
                connected = True
            elif error == 997:                       # ERROR_IO_PENDING
                # Wake up regularly so a shutdown is not stuck behind a client
                # that may never arrive.
                while not _server_stop.is_set():
                    if kernel32.WaitForSingleObject(accept_event, 500) != WAIT_TIMEOUT:
                        connected = True
                        break
        if not connected or _server_stop.is_set():
            try:
                kernel32.CancelIoEx(handle, None)
            except Exception:
                pass
            kernel32.CloseHandle(handle)
            continue
        threading.Thread(target=_serve_connection, args=(handle,),
                         name='TitanActionBusPeer', daemon=True).start()
    try:
        kernel32.CloseHandle(accept_event)
    except Exception:
        pass
    _log("accept loop stopped")


# --------------------------------------------------------------------------- #
# Public surface
# --------------------------------------------------------------------------- #
def start():
    """Bring the bus up in a background daemon thread. Idempotent."""
    global _server_thread
    if sys.platform != 'win32':
        return False
    if _server_thread is not None and _server_thread.is_alive():
        return True
    ensure_token()
    _server_stop.clear()
    _server_thread = threading.Thread(target=_accept_loop,
                                      name='TitanActionBus', daemon=True)
    _server_thread.start()
    return True


def stop():
    _server_stop.set()
    with _peers_lock:
        peers = list(_peers.values())
    for peer in peers:
        peer.close()


def is_running():
    return _server_thread is not None and _server_thread.is_alive()


def get_peer(addon_id):
    with _peers_lock:
        return _peers.get(addon_id)


def list_peers():
    with _peers_lock:
        return list(_peers.values())


def invoke(addon_id, action, args=None, timeout=_DEFAULT_TIMEOUT):
    """Run an action in a running add-on. Returns (ok, result_or_error)."""
    peer = get_peer(addon_id)
    if peer is None:
        return False, f"'{addon_id}' is not running (or has not joined the bus)"
    return peer.invoke(action, args or {}, timeout=timeout)
