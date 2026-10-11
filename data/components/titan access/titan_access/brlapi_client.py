# -*- coding: utf-8 -*-
"""BrlAPI - BRLTTY's client protocol - written in Python.

Why not ``brlapi-0.8.dll`` by ctypes: the Windows build of BRLTTY is
32-bit and Titan is 64-bit, so its DLL cannot be loaded here at all, and
on Linux the library is a package the user may not have. The protocol
itself is small and documented (``Programs/brlapi_protocol.h`` and
``brlapi_client.c`` of BRLTTY 6.9.1, read for this): a packet is a
32-bit big-endian SIZE, a 32-bit big-endian TYPE, then SIZE bytes. So the
reader speaks it itself, over whichever transport the server listens on:

* **Windows, local**: the named pipe ``\\\\.\\pipe\\BrlAPI<n>`` (``:n``);
* **Linux/macOS, local**: the Unix socket ``/var/lib/BrlAPI/<n>``;
* **TCP**: ``host:n`` is port ``4101 + n``.

Authorisation is ``none`` (what BRLTTY for Windows is built with, and
what Titan's own BRLTTY is started with) or ``key`` - the contents of
``/etc/brlapi.key``, which is what a Linux system BRLTTY asks for.

The connection is used from two threads: the reader WRITES lines, and a
key thread READS what the display's keys send. A synchronous pipe handle
serialises the two (a thread parked in ReadFile blocks the WriteFile
waiting behind it), so the key thread never blocks in a read: on a pipe
it asks ``PeekNamedPipe`` how much is there, on a socket it ``select``s.
"""

import os
import select
import socket
import struct
import sys
import threading
import time

PROTOCOL_VERSION = 8
SOCKET_PORT = 4101
UNIX_SOCKET_DIR = '/var/lib/BrlAPI'
PIPE_PREFIX = r'\\.\pipe\BrlAPI'
DEFAULT_KEY_FILE = '/etc/brlapi.key'

P_VERSION = ord('v')
P_AUTH = ord('a')
P_DRIVERNAME = ord('n')
P_MODELID = ord('d')
P_DISPLAYSIZE = ord('s')
P_ENTERTTYMODE = ord('t')
P_LEAVETTYMODE = ord('L')
P_KEY = ord('k')
P_WRITE = ord('w')
P_ACK = ord('A')
P_ERROR = ord('e')
P_EXCEPTION = ord('E')

AUTH_NONE = ord('N')
AUTH_KEY = ord('K')

WF_REGION = 0x02
WF_TEXT = 0x04
WF_CURSOR = 0x20
WF_CHARSET = 0x40

#: Key codes (``brlapi_keycodes.h`` / ``brlapi_constants.h``).
KEY_TYPE_MASK = 0xE0000000
KEY_TYPE_CMD = 0x20000000
KEY_TYPE_SYM = 0x00000000
KEY_CODE_MASK = 0x1FFFFFFF
CMD_BLK_MASK = 0x1FFF0000
CMD_ARG_MASK = 0x0000FFFF
FLG_SHIFT = 0x01 << 32
FLG_CONTROL = 0x04 << 32
FLG_META = 0x08 << 32

CMD_LNUP = 1
CMD_LNDN = 2
CMD_TOP = 9
CMD_BOT = 10
CMD_FWINLT = 23
CMD_FWINRT = 24
CMD_HOME = 29
CMD_RETURN = 31
BLK_ROUTE = 1
BLK_PASSDOTS = 34

SYM_NAMES = {
    0xFF08: 'backspace', 0xFF09: 'tab', 0xFF0D: 'enter', 0xFF1B: 'escape',
    0xFF50: 'home', 0xFF51: 'left', 0xFF52: 'up', 0xFF53: 'right',
    0xFF54: 'down', 0xFF55: 'pageup', 0xFF56: 'pagedown', 0xFF57: 'end',
    0xFFFF: 'delete',
}


class BrlApiError(Exception):
    pass


def parse_host(host):
    """``''`` / ``':n'`` / ``'name:n'`` / ``'name'`` -> (kind, where).

    kind is 'pipe', 'unix' or 'tcp'; where is a path or (host, port)."""
    host = (host or '').strip()
    name, _sep, number = host.rpartition(':') if ':' in host else (host, '', '0')
    try:
        n = int(number or 0)
    except ValueError:
        n = 0
    if not name:
        if sys.platform.startswith('win'):
            return 'pipe', PIPE_PREFIX + str(n)
        return 'unix', os.path.join(UNIX_SOCKET_DIR, str(n))
    return 'tcp', (name, SOCKET_PORT + n)


class _PipeTransport(object):
    """A Windows named pipe, read without ever blocking."""

    def __init__(self, path, timeout):
        import ctypes
        from ctypes import wintypes
        self._k = ctypes.WinDLL('kernel32', use_last_error=True)
        self._ct = ctypes
        k = self._k
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
        k.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        k.WriteFile.argtypes = k.ReadFile.argtypes
        k.PeekNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                    wintypes.LPVOID, ctypes.POINTER(wintypes.DWORD),
                                    wintypes.LPVOID]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        deadline = time.time() + timeout
        while True:
            h = k.CreateFileW(path, 0xC0000000, 0, None, 3, 0, None)
            if h and h != wintypes.HANDLE(-1).value:
                break
            err = ctypes.get_last_error()
            if err == 231 and time.time() < deadline:      # ERROR_PIPE_BUSY
                k.WaitNamedPipeW(path, 200)
                continue
            raise BrlApiError('cannot open %s (error %d)' % (path, err))
        self._h = h
        self._lock = threading.Lock()

    def available(self):
        n = self._ct.c_ulong(0)
        if not self._k.PeekNamedPipe(self._h, None, 0, None,
                                     self._ct.byref(n), None):
            raise BrlApiError('the BRLTTY pipe has closed')
        return n.value

    def wait_readable(self, timeout):
        deadline = time.time() + timeout
        while True:
            if self.available():
                return True
            if time.time() >= deadline:
                return False
            time.sleep(0.02)

    def recv(self, size):
        buf = self._ct.create_string_buffer(size)
        got = self._ct.c_ulong(0)
        with self._lock:
            ok = self._k.ReadFile(self._h, buf, size, self._ct.byref(got), None)
        if not ok or not got.value:
            raise BrlApiError('the BRLTTY pipe has closed')
        return buf.raw[:got.value]

    def send(self, data):
        done = self._ct.c_ulong(0)
        with self._lock:
            ok = self._k.WriteFile(self._h, data, len(data),
                                   self._ct.byref(done), None)
        if not ok or done.value != len(data):
            raise BrlApiError('could not write to BRLTTY')

    def close(self):
        if self._h:
            self._k.CloseHandle(self._h)
            self._h = None


class _SocketTransport(object):

    def __init__(self, kind, where, timeout):
        family = socket.AF_UNIX if kind == 'unix' else socket.AF_INET
        self._s = socket.socket(family, socket.SOCK_STREAM)
        self._s.settimeout(timeout)
        try:
            self._s.connect(where)
        except OSError as e:
            self._s.close()
            raise BrlApiError('cannot connect to %s: %s' % (where, e))
        self._s.settimeout(None)

    def wait_readable(self, timeout):
        r, _w, _x = select.select([self._s], [], [], timeout)
        return bool(r)

    def recv(self, size):
        data = self._s.recv(size)
        if not data:
            raise BrlApiError('BRLTTY closed the connection')
        return data

    def send(self, data):
        self._s.sendall(data)

    def close(self):
        try:
            self._s.close()
        except OSError:
            pass


class Connection(object):
    """One BrlAPI connection: open, take the display, write lines, read keys."""

    def __init__(self, host='', key_file=None, timeout=3.0):
        kind, where = parse_host(host)
        if kind == 'pipe':
            self._t = _PipeTransport(where, timeout)
        else:
            self._t = _SocketTransport(kind, where, timeout)
        self._buffer = b''
        self._read_lock = threading.Lock()
        self._keys = []
        self.columns = 0
        self.rows = 0
        self.driver = ''
        self.model = ''
        self._handshake(key_file)

    # -- packets --------------------------------------------------------- #
    def _send(self, ptype, payload=b''):
        self._t.send(struct.pack('>II', len(payload), ptype) + payload)

    def _read_exact(self, n, timeout):
        deadline = time.time() + timeout
        while len(self._buffer) < n:
            left = deadline - time.time()
            if left <= 0 or not self._t.wait_readable(left):
                raise BrlApiError('BRLTTY did not answer')
            self._buffer += self._t.recv(4096)
        data, self._buffer = self._buffer[:n], self._buffer[n:]
        return data

    def _read_packet(self, timeout):
        size, ptype = struct.unpack('>II', self._read_exact(8, timeout))
        return ptype, self._read_exact(size, timeout) if size else b''

    def _wait_for(self, wanted, timeout=3.0):
        """The next packet of type ``wanted``; keys arriving meanwhile are
        kept, an error or exception is raised."""
        with self._read_lock:
            while True:
                ptype, data = self._read_packet(timeout)
                if ptype == wanted:
                    return data
                if ptype == P_KEY and len(data) >= 8:
                    self._keys.append(_key_code(data))
                elif ptype in (P_ERROR, P_EXCEPTION):
                    code = struct.unpack('>I', data[:4])[0] if len(data) >= 4 else -1
                    raise BrlApiError('BRLTTY refused the request (error %d)' % code)

    def _request(self, ptype, timeout=3.0):
        self._send(ptype)
        return self._wait_for(ptype, timeout)

    # -- the handshake (brlapi__openConnection) ------------------------- #
    def _handshake(self, key_file):
        data = self._wait_for(P_VERSION)
        server = struct.unpack('>I', data[:4])[0]
        if server < PROTOCOL_VERSION:
            raise BrlApiError('BRLTTY speaks BrlAPI version %d, need %d'
                              % (server, PROTOCOL_VERSION))
        self._send(P_VERSION, struct.pack('>I', PROTOCOL_VERSION))
        data = self._wait_for(P_AUTH)
        methods = [struct.unpack('>I', data[i:i + 4])[0]
                   for i in range(0, len(data) - 3, 4)]
        for method in methods:
            if method == AUTH_NONE:
                break
            if method == AUTH_KEY:
                key = _read_key(key_file)
                if key is None:
                    continue
                self._send(P_AUTH, struct.pack('>I', AUTH_KEY) + key)
                self._wait_for(P_ACK)
                break
        else:
            raise BrlApiError('BRLTTY wants an authorisation this reader '
                              'cannot give (is %s readable?)'
                              % (key_file or DEFAULT_KEY_FILE))
        try:
            self.driver = self._request(P_DRIVERNAME).rstrip(b'\0').decode('utf-8', 'replace')
            self.model = self._request(P_MODELID).rstrip(b'\0').decode('utf-8', 'replace')
        except BrlApiError:
            pass
        size = self._request(P_DISPLAYSIZE)
        self.columns, self.rows = struct.unpack('>II', size[:8])

    # -- the display ---------------------------------------------------- #
    def enter_tty_mode(self):
        """Take the display (brlapi_enterTtyModeWithPath with an empty path
        and no driver name, so keys arrive as BRLTTY COMMANDS - the same
        meaning on every display)."""
        self._send(P_ENTERTTYMODE, struct.pack('>I', 0) + b'\0')
        self._wait_for(P_ACK)

    def leave_tty_mode(self):
        try:
            self._send(P_LEAVETTYMODE)
            self._wait_for(P_ACK, 1.0)
        except BrlApiError:
            pass

    def write(self, text, cursor=None):
        """Show ``text`` - Unicode braille cells, or text BRLTTY's own text
        table then turns into dots - filling the display, ``cursor`` the
        1-based cell to mark, or None."""
        size = max(1, self.columns * max(1, self.rows))
        line = str(text or '')[:size].ljust(size)
        body = line.encode('utf-8')
        flags = WF_REGION | WF_TEXT | WF_CHARSET
        payload = struct.pack('>II', 1, size)
        payload += struct.pack('>I', len(body)) + body
        if cursor is not None and 0 < cursor <= size:
            flags |= WF_CURSOR
            payload += struct.pack('>I', cursor)
        payload += bytes([5]) + b'utf-8'
        self._send(P_WRITE, struct.pack('>I', flags) + payload)

    def read_key(self, timeout):
        """The next key code, or None when nothing came within ``timeout``."""
        if self._keys:
            return self._keys.pop(0)
        with self._read_lock:
            if not self._buffer and not self._t.wait_readable(timeout):
                return None
            ptype, data = self._read_packet(1.0)
        if ptype == P_KEY and len(data) >= 8:
            return _key_code(data)
        if ptype in (P_ERROR, P_EXCEPTION):
            raise BrlApiError('BRLTTY reported an error')
        return None

    def close(self):
        try:
            self.leave_tty_mode()
        finally:
            self._t.close()


def _key_code(data):
    hi, lo = struct.unpack('>II', data[:8])
    return (hi << 32) | lo


def _read_key(path):
    for candidate in (path, os.environ.get('BRLAPI_KEY_FILE'), DEFAULT_KEY_FILE):
        if not candidate:
            continue
        try:
            with open(candidate, 'rb') as f:
                return f.read()
        except OSError:
            continue
    return None


def describe_key(code):
    """A key code as ``('command', name, argument)`` or ``('key', name, mods)``.

    name is a word the reader acts on: 'line_up', 'line_down', 'pan_left',
    'pan_right', 'top', 'bottom', 'home', 'route' (argument = 0-based cell),
    'dots' (argument = the dot pattern, bits 1..8), 'enter'; for a key, the
    name in ``SYM_NAMES`` or the character typed."""
    value = code & 0xFFFFFFFF
    kind = value & KEY_TYPE_MASK
    flags = code & ~0xFFFFFFFF
    if kind == KEY_TYPE_CMD:
        block = (value & CMD_BLK_MASK) >> 16
        arg = value & CMD_ARG_MASK
        if block == 0:
            name = {CMD_LNUP: 'line_up', CMD_LNDN: 'line_down',
                    CMD_FWINLT: 'pan_left', CMD_FWINRT: 'pan_right',
                    CMD_TOP: 'top', CMD_BOT: 'bottom', CMD_HOME: 'home',
                    CMD_RETURN: 'home'}.get(arg, 'command_%d' % arg)
            return ('command', name, None)
        if block == BLK_ROUTE:
            return ('command', 'route', arg)
        if block == BLK_PASSDOTS:
            return ('command', 'dots', arg & 0xFF)
        return ('command', 'block_%d' % block, arg)
    sym = value & KEY_CODE_MASK
    mods = set()
    if flags & FLG_SHIFT:
        mods.add('shift')
    if flags & FLG_CONTROL:
        mods.add('control')
    if flags & FLG_META:
        mods.add('alt')
    if sym in SYM_NAMES:
        return ('key', SYM_NAMES[sym], mods)
    if sym & 0xFF000000 == 0x01000000:              # Unicode keysym
        return ('key', chr(sym & 0x00FFFFFF), mods)
    if 0x20 <= sym < 0x100:
        return ('key', chr(sym), mods)
    return ('key', 'sym_%x' % sym, mods)
