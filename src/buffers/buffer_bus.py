# -*- coding: utf-8 -*-
"""
Titan Buffer System - producer-facing event bus.

This is the ONE public entry point every producer uses to feed the buffer
review system, regardless of where it lives:

  * In-process producers (titan-net client callbacks, Titan IM modules,
    components, launchers, widgets, the notification system) import this
    module and call push() / register_category() directly.

  * Out-of-process producers (data/applications/* apps and games, which run
    as separate child processes with src on sys.path) call the SAME push().
    Because the buffer state is shared in-memory and lives in the host
    process, push() is process-aware: in a child it transparently forwards
    the payload over a localhost IPC socket to the host, which applies it
    locally. App/game developers therefore just `from src.buffers import
    buffer_bus; buffer_bus.push(...)` and it works either way.

Design notes:
  * titan-net client callbacks are single-assignment, so producers must wrap
    (not replace) the existing callback and additionally call push().
  * A "ping" sound (ui/buffer_ping.ogg) is played only when a new element
    lands in the category AND buffer the user is currently reviewing
    (including that category's virtual "All" buffer). Background buffers stay
    silent.
  * Role detection: the host process calls start_host() once at startup; it
    starts the IPC server and exports TITAN_BUFFER_IPC=<port>:<token> into the
    environment so child processes inherit it. A process that did not call
    start_host() but sees that variable acts as a forwarding client. With no
    variable at all (standalone), push() simply writes locally.
"""

import os
import json
import socket
import threading

from src.buffers.buffer_system import get_buffer_manager

# Imported lazily to avoid sound/init ordering issues (see tsounds.py).
_play_sound = None

# Sound played when a new element arrives in the active category + buffer.
PING_SOUND = "ui/buffer_ping.ogg"

# Environment variable carrying "<port>:<token>" for the IPC bridge.
IPC_ENV = "TITAN_BUFFER_IPC"

_role = None          # 'host' once start_host() ran in this process
_host_server = None


def _ensure_play_sound():
    global _play_sound
    if _play_sound is None:
        try:
            from src.titan_core.sound import play_sound as _ps
            _play_sound = _ps
        except Exception as e:
            print(f"[BufferBus] play_sound unavailable: {e}")
            _play_sound = False  # mark as tried-and-failed
    return _play_sound or None


# --------------------------------------------------------------------------- #
#  Public producer API
# --------------------------------------------------------------------------- #
def register_category(category_id, name):
    """Create/rename a buffer category. Idempotent. Returns the category id.

    Any producer (titan-net, IM module, component, app, game, ...) may call
    this to own a top-level category in the review cycle.
    """
    try:
        # In a child process there is no shared state to register into; the
        # category is created lazily on the host by the first push().
        if _is_forwarding_client():
            return category_id
        get_buffer_manager().register_category(category_id, name)
    except Exception as e:
        print(f"[BufferBus] register_category error: {e}")
    return category_id


def ensure_buffer(category_id, buffer_id, name, kind=None):
    """Create/rename a buffer inside a category. Idempotent.

    `kind` is an optional source-type hint ("message", "notification", ...)
    used by the announcer when announce_widget_type is enabled.
    """
    try:
        if _is_forwarding_client():
            return buffer_id
        get_buffer_manager().ensure_buffer(category_id, buffer_id, name, kind=kind)
    except Exception as e:
        print(f"[BufferBus] ensure_buffer error: {e}")
    return buffer_id


def remove_category(category_id):
    """Remove a category (e.g. on logout / disconnect / module close). Idempotent."""
    try:
        if _is_forwarding_client():
            return
        get_buffer_manager().remove_category(category_id)
    except Exception as e:
        print(f"[BufferBus] remove_category error: {e}")


class _ModuleBufferAPI:
    """Per-owner convenience wrapper injected into Titan IM modules (and handy
    for components/apps). Binds a fixed category so callers only deal with
    buffers and elements:

        buffers.register_category("My Module")        # optional nice name
        buffers.ensure_buffer("chat", "Chat")
        buffers.push("chat", "hi", author="alice")
    """

    def __init__(self, category_id, category_name=None):
        self._cid = category_id
        self._cname = category_name or category_id

    def register_category(self, name=None):
        if name:
            self._cname = name
        return register_category(self._cid, self._cname)

    def ensure_buffer(self, buffer_id, name, kind=None):
        return ensure_buffer(self._cid, buffer_id, name, kind=kind)

    def push(self, buffer_id, text, author=None, kind=None, raw=None,
             buffer_name=None, timestamp=None):
        return push(self._cid, buffer_id, text, author=author, kind=kind,
                    raw=raw, category_name=self._cname,
                    buffer_name=buffer_name, timestamp=timestamp)


def make_module_api(category_id, category_name=None):
    """Return a category-bound buffer API (see _ModuleBufferAPI)."""
    return _ModuleBufferAPI(category_id, category_name)


def push(category_id, buffer_id, text, author=None, kind=None, raw=None,
         category_name=None, buffer_name=None, timestamp=None):
    """Append one element to (category, buffer) and ping if it is active.

    Categories/buffers are auto-created on first use. Pass category_name /
    buffer_name to give them human-readable labels (otherwise the ids are
    used). Safe to call from any thread and any process; never raises.

    Returns True if the element landed in the user's active category+buffer
    (always False in a forwarding child, where the host owns that decision).
    """
    payload = {
        "category_id": category_id,
        "buffer_id": buffer_id,
        "text": text,
        "author": author,
        "kind": kind,
        "category_name": category_name,
        "buffer_name": buffer_name,
        "timestamp": timestamp,
        "raw": raw,
    }

    if _is_forwarding_client():
        _forward(payload)
        return False

    return _push_local(**payload)


def _push_local(category_id, buffer_id, text, author=None, kind=None, raw=None,
                category_name=None, buffer_name=None, timestamp=None):
    """Apply a push to the in-process BufferManager and play the ping."""
    try:
        mgr = get_buffer_manager()
        if category_name:
            mgr.register_category(category_id, category_name)
        if buffer_name:
            mgr.ensure_buffer(category_id, buffer_id, buffer_name, kind=kind)

        is_active = mgr.add_element(category_id, buffer_id, text,
                                    author=author, kind=kind, raw=raw,
                                    timestamp=timestamp)

        if is_active:
            ps = _ensure_play_sound()
            if ps:
                try:
                    ps(PING_SOUND)
                except Exception as e:
                    print(f"[BufferBus] ping sound error: {e}")
        return is_active
    except Exception as e:
        print(f"[BufferBus] push error: {e}")
        return False


# --------------------------------------------------------------------------- #
#  IPC bridge (host server + forwarding client)
# --------------------------------------------------------------------------- #
def _is_forwarding_client():
    """True if this process should forward instead of writing locally."""
    return _role != 'host' and bool(os.environ.get(IPC_ENV))


def start_host():
    """Start the IPC server in the main process and export TITAN_BUFFER_IPC.

    Call once at application startup (before any apps/games are launched).
    Idempotent and best-effort; failures degrade to in-process-only operation.
    """
    global _role, _host_server
    if _role == 'host':
        return
    _role = 'host'
    try:
        _host_server = _BufferIPCServer()
        _host_server.start()
        os.environ[IPC_ENV] = f"{_host_server.port}:{_host_server.token}"
        print(f"[BufferBus] IPC host listening on 127.0.0.1:{_host_server.port}")
    except Exception as e:
        print(f"[BufferBus] start_host failed (in-process only): {e}")
        _host_server = None


def _forward(payload):
    info = os.environ.get(IPC_ENV)
    if not info:
        return False
    try:
        port_s, token = info.split(':', 1)
        payload = dict(payload)
        payload['_token'] = token
        # raw may be non-serialisable when sent from an app; drop it if so.
        try:
            data = json.dumps(payload)
        except (TypeError, ValueError):
            payload['raw'] = None
            data = json.dumps(payload)
        with socket.create_connection(('127.0.0.1', int(port_s)), timeout=1.0) as s:
            s.sendall((data + '\n').encode('utf-8'))
        return True
    except Exception as e:
        print(f"[BufferBus] forward error: {e}")
        return False


class _BufferIPCServer:
    """Localhost line-delimited JSON server applying forwarded pushes."""

    def __init__(self):
        self.token = os.urandom(16).hex()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(('127.0.0.1', 0))
        self._sock.listen(16)
        self.port = self._sock.getsockname()[1]
        self._running = True

    def start(self):
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while self._running:
            try:
                conn, _addr = self._sock.accept()
            except Exception:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn):
        try:
            buf = b''
            with conn:
                conn.settimeout(5.0)
                while True:
                    data = conn.recv(65536)
                    if not data:
                        break
                    buf += data
                    while b'\n' in buf:
                        line, buf = buf.split(b'\n', 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            payload = json.loads(line.decode('utf-8'))
                            if payload.pop('_token', None) != self.token:
                                continue  # reject unauthenticated payloads
                            _push_local(**payload)
                        except Exception as e:
                            print(f"[BufferBus] bad IPC payload: {e}")
        except Exception:
            pass
