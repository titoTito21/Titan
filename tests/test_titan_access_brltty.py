# -*- coding: utf-8 -*-
"""Titan Access's braille display, through BRLTTY.

There was no way to choose a display: `braille.py` loaded a brlapi DLL off
PATH (a 32-bit one on Windows, which a 64-bit Titan cannot load) and only
wrote when it was ALREADY connected - and nothing ever connected. Now the
reader speaks BrlAPI itself (`brlapi_client`), starts BRLTTY with the
display and port the user chose (`brltty_host`), and the display's keys
drive the reader.

The protocol tests talk to a fake BrlAPI server over TCP, so they run on
Windows and Linux alike. The live test starts a real BRLTTY with its
virtual `xw` display: the bundled one on Windows, or the one `TITAN_BRLTTY`
names (or the system's) on Linux. Nothing here touches the user's stores.

Run directly.
"""
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest

os.environ['APPDATA'] = tempfile.mkdtemp(prefix='ta_brl_')
if not sys.platform.startswith('win'):
    os.environ.setdefault('HOME', os.environ['APPDATA'])

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'data', 'components', 'titan access'))

from titan_access import brlapi_client as bc        # noqa: E402
from titan_access import brltty_host, braille       # noqa: E402
from titan_access import settings_schema            # noqa: E402


class FakeServer(threading.Thread):
    """A BrlAPI 8 server for one client, recording what it is sent."""

    def __init__(self, key=None, columns=20):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.key = key
        self.columns = columns
        self.writes = []
        self.keys_to_send = []
        self.ready = threading.Event()

    def _send(self, conn, ptype, payload=b''):
        conn.sendall(struct.pack('>II', len(payload), ptype) + payload)

    def _recv(self, conn):
        head = b''
        while len(head) < 8:
            part = conn.recv(8 - len(head))
            if not part:
                return None, None
            head += part
        size, ptype = struct.unpack('>II', head)
        data = b''
        while len(data) < size:
            data += conn.recv(size - len(data))
        return ptype, data

    def run(self):
        conn, _a = self.sock.accept()
        self._send(conn, bc.P_VERSION, struct.pack('>I', 8))
        self._recv(conn)
        if self.key is None:
            self._send(conn, bc.P_AUTH, struct.pack('>I', bc.AUTH_NONE))
        else:
            self._send(conn, bc.P_AUTH, struct.pack('>I', bc.AUTH_KEY))
            ptype, data = self._recv(conn)
            if data[4:] != self.key:
                self._send(conn, bc.P_ERROR, struct.pack('>I', 6))
                return
            self._send(conn, bc.P_ACK)
        while True:
            ptype, data = self._recv(conn)
            if ptype is None:
                return
            if ptype == bc.P_DRIVERNAME:
                self._send(conn, ptype, b'Fake\0')
            elif ptype == bc.P_MODELID:
                self._send(conn, ptype, b'model\0')
            elif ptype == bc.P_DISPLAYSIZE:
                self._send(conn, ptype, struct.pack('>II', self.columns, 1))
            elif ptype in (bc.P_ENTERTTYMODE, bc.P_LEAVETTYMODE):
                self._send(conn, bc.P_ACK)
                if ptype == bc.P_ENTERTTYMODE:
                    for code in self.keys_to_send:
                        self._send(conn, bc.P_KEY,
                                   struct.pack('>II', code >> 32, code & 0xFFFFFFFF))
            elif ptype == bc.P_WRITE:
                self.writes.append(_decode_write(data))
                self.ready.set()


def _decode_write(data):
    flags = struct.unpack('>I', data[:4])[0]
    p = 4
    out = {}
    if flags & bc.WF_REGION:
        out['region'] = struct.unpack('>II', data[p:p + 8])
        p += 8
    if flags & bc.WF_TEXT:
        n = struct.unpack('>I', data[p:p + 4])[0]
        out['text'] = data[p + 4:p + 4 + n].decode('utf-8')
        p += 4 + n
    if flags & bc.WF_CURSOR:
        out['cursor'] = struct.unpack('>I', data[p:p + 4])[0]
        p += 4
    if flags & bc.WF_CHARSET:
        n = data[p]
        out['charset'] = data[p + 1:p + 1 + n].decode()
    return out


class TheProtocolIsBrlApis(unittest.TestCase):

    def test_a_line_reaches_the_display_padded_with_its_cursor(self):
        server = FakeServer()
        server.start()
        c = bc.Connection('127.0.0.1:%d' % (server.port - bc.SOCKET_PORT))
        self.assertEqual((c.driver, c.columns), ('Fake', 20))
        c.enter_tty_mode()
        c.write('\u2803\u2817\u2807', cursor=2)
        self.assertTrue(server.ready.wait(3))
        w = server.writes[0]
        self.assertEqual(w['region'], (1, 20))
        self.assertEqual(w['text'], '\u2803\u2817\u2807'.ljust(20))
        self.assertEqual(w['cursor'], 2)
        self.assertEqual(w['charset'], 'utf-8')
        c.close()

    def test_a_key_file_is_what_a_system_brltty_asks_for(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, 'brlapi.key')
        with open(path, 'wb') as f:
            f.write(b'secret')
        server = FakeServer(key=b'secret')
        server.start()
        c = bc.Connection('127.0.0.1:%d' % (server.port - bc.SOCKET_PORT),
                          key_file=path)
        self.assertEqual(c.columns, 20)
        c.close()

    def test_the_displays_keys_are_read(self):
        server = FakeServer()
        route = bc.KEY_TYPE_CMD | (bc.BLK_ROUTE << 16) | 5
        server.keys_to_send = [route, bc.KEY_TYPE_CMD | bc.CMD_FWINRT]
        server.start()
        c = bc.Connection('127.0.0.1:%d' % (server.port - bc.SOCKET_PORT))
        c.enter_tty_mode()
        got = [c.read_key(2), c.read_key(2)]
        self.assertEqual(bc.describe_key(got[0]), ('command', 'route', 5))
        self.assertEqual(bc.describe_key(got[1]), ('command', 'pan_right', None))
        c.close()

    def test_keys_are_described(self):
        self.assertEqual(bc.describe_key(bc.KEY_TYPE_CMD | (bc.BLK_PASSDOTS << 16) | 1),
                         ('command', 'dots', 1))
        self.assertEqual(bc.describe_key(0xFF0D), ('key', 'enter', set()))
        self.assertEqual(bc.describe_key(bc.FLG_CONTROL | ord('s')),
                         ('key', 's', {'control'}))

    def test_where_brltty_listens(self):
        self.assertEqual(bc.parse_host('localhost:2'), ('tcp', ('localhost', 4103)))
        kind, where = bc.parse_host(':7')
        if sys.platform.startswith('win'):
            self.assertEqual((kind, where), ('pipe', r'\\.\pipe\BrlAPI7'))
        else:
            self.assertEqual((kind, where), ('unix', '/var/lib/BrlAPI/7'))


class TheDisplayIsChosen(unittest.TestCase):

    def test_display_and_port_are_settings(self):
        displays = [v for v, _k in settings_schema.options(
            settings_schema.find('Braille', 'Display'))]
        ports = [v for v, _k in settings_schema.options(
            settings_schema.find('Braille', 'Port'))]
        for code in ('none', 'system', 'auto', 'bm', 'fs', 'hw', 'ht', 'hm', 'eu'):
            self.assertIn(code, displays)
        for port in ('auto', 'usb', 'bluetooth', 'hid'):
            self.assertIn(port, ports)

    def test_a_port_is_a_brltty_device(self):
        self.assertEqual(brltty_host.device_for('auto'), 'usb:,bluetooth:')
        self.assertEqual(brltty_host.device_for('hid'), 'hid:')
        self.assertEqual(brltty_host.device_for('COM3'), 'serial:COM3')

    def test_brltty_is_started_without_screen_or_speech_on_a_channel_of_its_own(self):
        if brltty_host.executable() is None:
            self.skipTest('no BRLTTY here')
        argv, host, key = brltty_host.command('bm', 'usb')
        self.assertEqual(argv[argv.index('-b') + 1], 'bm')
        self.assertEqual(argv[argv.index('-d') + 1], 'usb:')
        self.assertEqual(argv[argv.index('-x') + 1], 'no')
        self.assertEqual(argv[argv.index('-s') + 1], 'no')
        api = argv[argv.index('-A') + 1]
        if sys.platform.startswith('win'):
            self.assertEqual(host, ':7')
            self.assertIn('auth=none', api)
        else:
            # A user-run BRLTTY cannot use /var/lib/BrlAPI: the loopback,
            # with a key only this user can read.
            self.assertEqual(host, '127.0.0.1:7')
            self.assertIn('auth=keyfile:', api)
            self.assertEqual(os.stat(key).st_mode & 0o077, 0)

    def test_none_and_system_start_nothing(self):
        self.assertIsNone(brltty_host.command('none', 'auto'))
        self.assertIsNone(brltty_host.command('system', 'auto'))


class _FakeHost(object):
    def __init__(self, columns=10):
        class C(object):
            pass
        self.connection = C()
        self.connection.columns = columns
        self.connection.rows = 1
        self.written = []
        self.display, self.port = 'bm', 'auto'

    def write(self, cells, cursor=None):
        self.written.append(cells)
        return True


class TheDisplaysKeysDriveTheReader(unittest.TestCase):

    def setUp(self):
        from titan_access.portable import readerApi
        self.readerApi = readerApi
        self.saved = {n: getattr(readerApi, n) for n in
                      ('send_key', 'type_text', 'focus', 'do_action')}
        self.calls = []
        readerApi.send_key = lambda name: self.calls.append(('key', name)) or True
        readerApi.type_text = lambda text: self.calls.append(('type', text)) or True
        readerApi.focus = lambda: 'focused'
        readerApi.do_action = lambda obj: self.calls.append(('press', obj)) or True
        self.display = braille._Display()
        self.display.host = _FakeHost(10)
        self.display.ensure = lambda: True

    def tearDown(self):
        for name, fn in self.saved.items():
            setattr(self.readerApi, name, fn)

    def test_a_long_line_is_panned_a_display_at_a_time(self):
        self.display.show('\u2801' * 25, 'x' * 25)
        self.assertEqual(len(self.display.host.written[-1]), 10)
        self.assertTrue(self.display.on_key(('command', 'pan_right', None)))
        self.assertEqual(self.display.offset, 10)
        self.assertTrue(self.display.on_key(('command', 'pan_right', None)))
        self.assertEqual(self.display.host.written[-1], '\u2801' * 5)
        self.assertFalse(self.display.on_key(('command', 'pan_right', None)))
        self.assertTrue(self.display.on_key(('command', 'pan_left', None)))
        self.assertEqual(self.display.offset, 10)

    def test_line_keys_routing_and_typing_reach_the_program(self):
        d = self.display
        d.on_key(('command', 'line_down', None))
        d.on_key(('command', 'route', 3))
        d.on_key(('key', 'enter', set()))
        d.on_key(('key', 's', {'control'}))
        d.on_key(('key', 'x', set()))
        self.assertEqual(self.calls, [('key', 'downArrow'), ('press', 'focused'),
                                      ('key', 'enter'), ('key', 'control+s'),
                                      ('type', 'x')])

    def test_dots_typed_in_braille_are_letters(self):
        if braille._load() is None:
            self.skipTest('no liblouis here')
        self.display.on_key(('command', 'dots', 0x01))
        self.assertEqual(self.calls, [('type', 'a')])

    def test_back_translation_knows_polish(self):
        if braille._load() is None:
            self.skipTest('no liblouis here')
        self.assertEqual(braille.back_translate(braille.translate('kot', 'pl'), 'pl'), 'kot')
        self.assertEqual(braille.back_translate('\u2821', 'pl'), '\u0105')


class ARealBrlttyShowsTheCells(unittest.TestCase):
    """The bundled BRLTTY on Windows, the system's (or TITAN_BRLTTY) on Linux,
    with its virtual xw display - which needs a desktop."""

    def test_open_write_and_close(self):
        if brltty_host.executable() is None:
            self.skipTest('no BRLTTY here')
        if not sys.platform.startswith('win') and not os.environ.get('DISPLAY'):
            self.skipTest('the xw display needs a desktop')
        host = brltty_host.Host()
        try:
            if not host.open('xw', 'auto', wait=15):
                self.skipTest('BRLTTY has no xw driver here: %s' % host.why)
            self.assertGreater(host.report()['cells'], 0)
            self.assertTrue(host.write('\u2803\u2817\u2807', cursor=1))
            # Opening the same display again keeps the connection.
            connection = host.connection
            self.assertTrue(host.open('xw', 'auto'))
            self.assertIs(host.connection, connection)
        finally:
            host.close()
        self.assertFalse(host.report()['running'])


if __name__ == '__main__':
    unittest.main()
