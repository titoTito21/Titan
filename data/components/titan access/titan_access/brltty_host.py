# -*- coding: utf-8 -*-
"""The braille display the user chose, through BRLTTY.

BRLTTY knows forty families of braille displays - USB, Bluetooth, HID and
serial - and BrlAPI is how another program borrows one. So choosing a
display in Titan Access is choosing what BRLTTY is started with:

* **'none'**: no display; the braille viewer alone (the default);
* **'system'**: a BRLTTY that is already running - a Linux distribution's
  ``brltty.service``, or BRLTTY for Windows installed as a service - which
  Titan Access only connects to, at ``:0``;
* **'auto'** or a **driver code** (``bm`` Baum, ``fs`` Freedom Scientific,
  ``hw`` HumanWare, ``ht`` HandyTech, ``hm`` HIMS, ...): Titan Access starts
  BRLTTY ITSELF, with that driver, on the chosen port, with no screen
  driver and no speech (the reader is the screen reader; BRLTTY only drives
  the device), and connects to it on a channel of its own.

Where BRLTTY comes from:

* **Windows**: this component's own ``lib/brltty`` (BRLTTY 6.9.1 for
  Windows: ``bin/brltty.exe`` and the key tables under ``etc/brltty``).
  Nothing to install - a feature of Titan Access needs nothing outside its
  folder. A USB display without its maker's driver needs the LibUSB
  driver once: ``lib/brltty/bin/brltty-libusb-1.0.inf``.
* **Linux**: the system's ``brltty`` (the package every distribution has),
  started as the user. A user-run BRLTTY cannot create the system socket
  in ``/var/lib/BrlAPI``, so it listens on TCP on the loopback only, with
  a random key file of the user's own (mode 600) - no other user can write
  to the display.

Titan Access's own BRLTTY listens on ``:7`` (pipe ``BrlAPI7`` / port 4108),
so it never collides with a system BRLTTY on ``:0``.
"""

import os
import secrets
import shutil
import subprocess
import sys
import threading
import time

from . import brlapi_client

IS_WINDOWS = sys.platform.startswith('win')
OWN_CHANNEL = 7

#: BRLTTY's braille drivers (``braille-driver.csv`` of 6.9.1), less 'ba'
#: (a BrlAPI CLIENT, not a display) and 'lb'/'tt' (no device).
DRIVERS = ('al', 'at', 'bc', 'bd', 'bl', 'bm', 'bn', 'cb', 'ce', 'cn', 'dp',
           'ec', 'eu', 'fa', 'fs', 'hd', 'hm', 'ht', 'hw', 'ic', 'ir', 'lt',
           'mb', 'md', 'mm', 'mn', 'mt', 'np', 'pg', 'pm', 'sk', 'tn', 'ts',
           'vd', 'vo', 'vs', 'xw')
DISPLAYS = ('none', 'system', 'auto') + DRIVERS

#: Port values as kept in the settings, and the BRLTTY device they mean.
if IS_WINDOWS:
    SERIAL_PORTS = tuple('COM%d' % n for n in range(1, 13))
else:
    SERIAL_PORTS = ('/dev/ttyUSB0', '/dev/ttyUSB1', '/dev/ttyACM0',
                    '/dev/ttyS0', '/dev/ttyS1', '/dev/rfcomm0')
PORTS = ('auto', 'usb', 'bluetooth', 'hid') + SERIAL_PORTS

_COMPONENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED = os.path.join(_COMPONENT, 'lib', 'brltty')


def device_for(port):
    """The ``-d`` argument for a port setting."""
    port = (port or 'auto').strip()
    if port == 'auto':
        return 'usb:,bluetooth:'
    if port in ('usb', 'bluetooth', 'hid'):
        return port + ':'
    return 'serial:' + port


def executable():
    """The BRLTTY to start, or None."""
    override = os.environ.get('TITAN_BRLTTY')
    if override and os.path.isfile(override):
        return override
    if IS_WINDOWS:
        path = os.path.join(BUNDLED, 'bin', 'brltty.exe')
        return path if os.path.isfile(path) else None
    found = shutil.which('brltty')
    if found:
        return found
    for path in ('/usr/bin/brltty', '/usr/sbin/brltty', '/sbin/brltty',
                 '/usr/local/bin/brltty'):
        if os.path.isfile(path):
            return path
    return None


def _data_dir():
    try:
        from .portable import readerHome
        base = readerHome.folder()
    except Exception:                                # noqa: BLE001
        base = os.path.join(os.path.expanduser('~'), '.titan_access')
    path = os.path.join(base, 'brltty')
    os.makedirs(path, exist_ok=True)
    return path


def _log_path():
    try:
        from . import log
        folder = os.path.dirname(log.path())
    except Exception:                                # noqa: BLE001
        folder = _data_dir()
    return os.path.join(folder, 'brltty.log')


def _own_key(folder):
    """A key file only this user can read, made once."""
    path = os.path.join(folder, 'brlapi.key')
    if not os.path.isfile(path):
        with open(path, 'wb') as f:
            f.write(secrets.token_hex(32).encode('ascii'))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def command(display, port, channel=OWN_CHANNEL):
    """``(argv, host, key file)`` to start BRLTTY for a display, or None."""
    exe = executable()
    if exe is None or display in ('none', 'system'):
        return None
    folder = _data_dir()
    conf = os.path.join(folder, 'empty.conf')
    if not os.path.isfile(conf):
        open(conf, 'w').close()
    argv = [exe, '-n', '-q',
            '-b', display or 'auto', '-d', device_for(port),
            '-x', 'no', '-s', 'no',
            '-f', conf,
            '-F', os.path.join(folder, 'brltty.prefs'),
            '-W', folder,
            '-P', os.path.join(folder, 'brltty.pid'),
            '-L', _log_path(), '-l', 'notice']
    if IS_WINDOWS:
        argv += ['-T', os.path.join(BUNDLED, 'etc', 'brltty')]
        host, key = ':%d' % channel, None
        argv += ['-A', 'host=%s,auth=none' % host]
    else:
        # A BRLTTY unpacked somewhere of its own (a portable copy, like the
        # portable Wine under ~/wine) finds its drivers and tables beside
        # itself, not under /lib and /etc.
        root = os.path.dirname(os.path.dirname(os.path.abspath(exe)))
        if root not in ('/', '/usr', '/usr/local'):
            drivers = os.path.join(root, 'lib', 'brltty')
            tables = os.path.join(root, 'etc', 'brltty')
            if os.path.isdir(drivers):
                argv += ['-D', drivers]
            if os.path.isdir(tables):
                argv += ['-T', tables]
        key = _own_key(folder)
        host = '127.0.0.1:%d' % channel
        argv += ['-A', 'host=%s,auth=keyfile:%s' % (host, key)]
    return argv, host, key


class Host(object):
    """Starts (or finds) BRLTTY and keeps one BrlAPI connection to it."""

    def __init__(self):
        self.process = None
        self.connection = None
        self.display = 'none'
        self.port = 'auto'
        self.why = ''
        self._lock = threading.RLock()

    def report(self):
        c = self.connection
        return {
            'display': self.display, 'port': self.port,
            'connected': c is not None,
            'driver': c.driver if c else '', 'model': c.model if c else '',
            'cells': c.columns if c else 0,
            'brltty': executable() or '',
            'running': bool(self.process and self.process.poll() is None),
            'why': self.why,
        }

    #: BRLTTY sometimes takes 7-8 s to put its BrlAPI pipe up (measured on
    #: Windows: about one start in five), and finding a Bluetooth display
    #: takes longer still. It happens on a thread of its own, so the reader
    #: never waits for it.
    OPEN_WAIT = 20.0

    def open(self, display, port, wait=None):
        """Connect to the display the settings name; True when connected.

        Re-uses the connection when the choice has not changed."""
        with self._lock:
            if (self.connection is not None and display == self.display
                    and port == self.port and self._alive()):
                return True
            self.close()
            self.display, self.port = display, port
            if display == 'none':
                self.why = 'no display chosen'
                return False
            if display == 'system':
                return self._connect(':0' if IS_WINDOWS else '', None, 2.0)
            spec = command(display, port)
            if spec is None:
                self.why = ('BRLTTY is not installed (install the brltty '
                            'package)' if not IS_WINDOWS else
                            'lib/brltty is missing from Titan Access')
                return False
            argv, host, key = spec
            self._cancel_stale(argv)
            try:
                self.process = subprocess.Popen(
                    argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000 if IS_WINDOWS else 0)
            except OSError as e:
                self.why = 'BRLTTY could not be started: %s' % e
                return False
            return self._connect(host, key, wait or self.OPEN_WAIT)

    @staticmethod
    def _cancel_stale(argv):
        """Stop a BRLTTY of ours left running (Titan crashed, or was killed):
        it still holds channel 7, a new one cannot take it, and the reader
        would connect to the OLD instance - the wrong display, or a window
        nobody looks at. ``brltty -C`` cannot do it on Windows (measured: it
        exits 4 looking for //etc/brltty.conf), so the pid file is read and
        that process stopped - only when it really IS a brltty, because a
        pid is reused the moment its process ends."""
        pid_file = argv[argv.index('-P') + 1]
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip() or 0)
        except (OSError, ValueError):
            return
        if pid > 0:
            try:
                import psutil
                proc = psutil.Process(pid)
                if 'brltty' in (proc.name() or '').lower():
                    proc.terminate()
                    proc.wait(3)
            except Exception:                        # noqa: BLE001
                pass
        try:
            os.remove(pid_file)
        except OSError:
            pass

    def _alive(self):
        return self.process is None or self.process.poll() is None

    def _connect(self, host, key, wait):
        deadline = time.time() + wait
        last = None
        while time.time() < deadline:
            if self.process is not None and self.process.poll() is not None:
                last = 'BRLTTY stopped (no display found on that port?) - see brltty.log'
                break
            try:
                connection = brlapi_client.Connection(host, key_file=key)
                if connection.columns <= 0:
                    connection.close()
                    last = 'the display reports no cells'
                    time.sleep(0.5)
                    continue
                connection.enter_tty_mode()
                self.connection = connection
                self.why = ''
                return True
            except brlapi_client.BrlApiError as e:
                last = str(e)
                time.sleep(0.3)
        self.why = last or 'BRLTTY did not answer'
        self._stop_process()
        return False

    def write(self, cells, cursor=None):
        with self._lock:
            c = self.connection
            if c is None:
                return False
            try:
                c.write(cells, cursor)
                return True
            except (brlapi_client.BrlApiError, OSError) as e:
                self.why = str(e)
                self._drop()
                return False

    def read_key(self, timeout):
        c = self.connection
        if c is None:
            time.sleep(timeout)
            return None
        try:
            return c.read_key(timeout)
        except (brlapi_client.BrlApiError, OSError) as e:
            self.why = str(e)
            with self._lock:
                self._drop()
            return None

    def _drop(self):
        c, self.connection = self.connection, None
        if c is not None:
            try:
                c.close()
            except Exception:                        # noqa: BLE001
                pass

    def _stop_process(self):
        p, self.process = self.process, None
        if p is not None and p.poll() is None:
            try:
                p.terminate()
                p.wait(3)
            except Exception:                        # noqa: BLE001
                try:
                    p.kill()
                except Exception:                    # noqa: BLE001
                    pass

    def close(self):
        with self._lock:
            self._drop()
            self._stop_process()
