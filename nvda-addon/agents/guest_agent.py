#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runs INSIDE a virtual machine's guest and says what it sees to the host.

**Read this first: you probably do not need it.** The reader on the host
already reads a guest with nothing installed in it at all - it takes the
picture out of the virtual machine's own window (9 ms, measured) and reads
it with a model running on the host, following what is HIGHLIGHTED as the
arrow keys move. That works on a Windows 95 guest, on Linux, on macOS, on a
guest that has no networking and on one whose operating system nobody has
ever written a screen reader for, because a picture is a picture.

What an agent adds is the difference between a picture and the WORDS: exact
text, instantly, with no model and no guessing, and the name of a control
that is drawn as an icon with no text near it at all. That is worth having
and it is worth nobody's afternoon, so this is small, optional, and stops
being needed the moment it is not running.

    python guest_agent.py                 # VMware Tools, no network at all
    python guest_agent.py --transport tcp --host 192.168.1.5 --token <key>

**Two ways back to the host, and the first needs no network.**

* `rpctool` - VMware Tools' own channel. The agent runs
  `vmware-rpctool "info-set guestinfo.titan.say ..."` and the reader picks
  it up with `vmrun readVariable`. No port, no address, no firewall, and
  nothing to configure on either side: if VMware Tools is running, this
  works. Measured end to end against a live guest on this machine.
* `tcp` - one line of JSON per thing seen, to the port the reader listens
  on, carrying the key from its settings page (**The agent's key...**).
  For a guest whose tools are not VMware's, or a game engine, where there
  is no hypervisor channel to borrow.

**How it reads the guest**, in descending order of trust, which is the same
order the reader uses on the host - and each tier is a whole platform, so
the one that answers is whichever one this guest has:

* **Windows**: UI Automation, then MSAA (`AccessibleObjectFromPoint`, which
  is what a Windows from the 2000s answers and still the best thing on one),
  then the window's own text.
* **Linux**: AT-SPI through `pyatspi`, then the focused window's name.
* **macOS**: the Accessibility API through `pyobjc`.
* **Anything else**, or a guest with none of that installed: it says so, in
  one sentence, and stops - rather than running and reporting nothing, which
  from the outside is indistinguishable from a broken channel.

A guest older than every accessibility layer - Windows 95 is the case, and
it is a real one - has nothing here to read. That is not a failure of the
channel: it is what that operating system knows about itself. Read it as a
picture from the host, which is what the reader does by default.

Nothing here speaks. It sends words; the reader on the host says them in the
user's own voice, at their rate, through their synthesiser.
"""

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time

#: The guest variable the reader watches. VMware's own namespace.
SAY_VAR = 'guestinfo.titan.say'


# --------------------------------------------------------------------------- #
# Reading this guest
# --------------------------------------------------------------------------- #
class NoReader(object):
    """A guest with no accessibility layer, saying so rather than nothing."""

    why = 'this guest has no accessibility layer this agent can read'

    def at_point(self, x, y):
        return ''

    def focused(self):
        return ''


class WindowsReader(object):
    """UI Automation, then MSAA, then the window's own text."""

    why = ''

    def __init__(self):
        import ctypes
        self.ctypes = ctypes
        self.user32 = ctypes.windll.user32
        self.user32.GetForegroundWindow.restype = ctypes.c_void_p
        self.user32.WindowFromPoint.restype = ctypes.c_void_p
        self.user32.GetFocus.restype = ctypes.c_void_p
        self.uia = self._open_uia()

    @staticmethod
    def _open_uia():
        try:
            import comtypes.client
            import comtypes.gen.UIAutomationClient as client
            return comtypes.client.CreateObject(
                '{ff48dba4-60ef-4201-aa87-54103eef594e}',
                interface=client.IUIAutomation)
        except Exception:
            return None

    # --------------------------------------------------------- by point
    def at_point(self, x, y):
        for route in (self._uia_at, self._msaa_at, self._window_at):
            try:
                said = route(x, y)
            except Exception:
                said = ''
            if said:
                return said
        return ''

    def _point(self, x, y):
        from ctypes import wintypes
        return wintypes.POINT(int(x), int(y))

    def _uia_at(self, x, y):
        if self.uia is None:
            return ''
        element = self.uia.ElementFromPoint(self._point(x, y))
        if element is None:
            return ''
        return _join(str(element.CurrentName or ''),
                     str(element.CurrentLocalizedControlType or ''))

    def _msaa_at(self, x, y):
        import comtypes.automation
        import comtypes.client
        oleacc = self.ctypes.oledll.oleacc
        child = comtypes.automation.VARIANT()
        accessible = self.ctypes.POINTER(self.ctypes.c_void_p)()
        oleacc.AccessibleObjectFromPoint(
            self._point(x, y), self.ctypes.byref(accessible),
            self.ctypes.byref(child))
        obj = comtypes.client.GetBestInterface(accessible)
        return _join(str(obj.accName(child) or ''),
                     _role_name(obj.accRole(child)))

    def _window_at(self, x, y):
        handle = self.user32.WindowFromPoint(self._point(x, y))
        return self._words(handle) if handle else ''

    # ------------------------------------------------------ by keyboard
    def focused(self):
        if self.uia is not None:
            try:
                element = self.uia.GetFocusedElement()
                if element is not None:
                    said = _join(str(element.CurrentName or ''),
                                 str(element.CurrentLocalizedControlType or ''))
                    if said:
                        return said
            except Exception:
                pass
        handle = self.user32.GetFocus() or self.user32.GetForegroundWindow()
        return self._words(handle) if handle else ''

    def _words(self, handle):
        """A window's own text and class - the last thing that answers."""
        text = self.ctypes.create_unicode_buffer(512)
        self.user32.GetWindowTextW(self.ctypes.c_void_p(handle), text, 512)
        klass = self.ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(self.ctypes.c_void_p(handle), klass, 256)
        return _join(str(text.value or ''), str(klass.value or ''))

    def pointer(self):
        from ctypes import wintypes
        point = wintypes.POINT()
        self.user32.GetCursorPos(self.ctypes.byref(point))
        return point.x, point.y


class AtspiReader(object):
    """Linux: AT-SPI, which is what every toolkit there reports through."""

    why = ''

    def __init__(self):
        import pyatspi
        self.pyatspi = pyatspi
        self.registry = pyatspi.Registry
        self.desktop = pyatspi.Registry.getDesktop(0)

    def at_point(self, x, y):
        # AT-SPI answers a point per application, so the applications are
        # asked in turn and the first that owns the point answers. There is
        # no desktop-wide "what is at this point" in AT-SPI at all.
        for application in self.desktop:
            try:
                found = application.queryComponent().getAccessibleAtPoint(
                    int(x), int(y), self.pyatspi.DESKTOP_COORDS)
            except Exception:
                found = None
            if found is not None:
                said = _join(str(found.name or ''),
                             str(found.getRoleName() or ''))
                if said:
                    return said
        return ''

    def focused(self):
        try:
            found = self.registry.getDesktop(0)
        except Exception:
            return ''
        for application in found:
            try:
                for window in application:
                    states = window.getState()
                    if states.contains(self.pyatspi.STATE_ACTIVE):
                        return _join(str(window.name or ''),
                                     str(window.getRoleName() or ''))
            except Exception:
                continue
        return ''

    def pointer(self):
        # X has no portable pointer call without a toolkit; xdotool is the
        # one thing that is on nearly every desktop Linux.
        if not shutil.which('xdotool'):
            return None
        try:
            done = subprocess.run(['xdotool', 'getmouselocation', '--shell'],
                                  capture_output=True, timeout=2)
        except Exception:
            return None
        found = {}
        for line in (done.stdout or b'').decode('utf-8', 'replace').split():
            if '=' in line:
                key, value = line.split('=', 1)
                found[key] = value
        try:
            return int(found['X']), int(found['Y'])
        except (KeyError, ValueError):
            return None


class MacReader(object):
    """macOS: the Accessibility API, through pyobjc."""

    why = ''

    def __init__(self):
        from ApplicationServices import AXUIElementCreateSystemWide
        from ApplicationServices import AXUIElementCopyElementAtPosition
        from ApplicationServices import AXUIElementCopyAttributeValue
        import Quartz
        self.system = AXUIElementCreateSystemWide()
        self.at_position = AXUIElementCopyElementAtPosition
        self.attribute = AXUIElementCopyAttributeValue
        self.quartz = Quartz

    def _value(self, element, name):
        try:
            error, value = self.attribute(element, name, None)
        except Exception:
            return ''
        return '' if error else str(value or '')

    def at_point(self, x, y):
        try:
            error, element = self.at_position(self.system, x, y, None)
        except Exception:
            return ''
        if error or element is None:
            return ''
        return _join(self._value(element, 'AXTitle') or
                     self._value(element, 'AXValue'),
                     self._value(element, 'AXRoleDescription'))

    def focused(self):
        error, element = self.attribute(
            self.system, 'AXFocusedUIElement', None)
        if error or element is None:
            return ''
        return _join(self._value(element, 'AXTitle') or
                     self._value(element, 'AXValue'),
                     self._value(element, 'AXRoleDescription'))

    def pointer(self):
        where = self.quartz.NSEvent.mouseLocation()
        screen = self.quartz.CGDisplayBounds(
            self.quartz.CGMainDisplayID()).size.height
        return int(where.x), int(screen - where.y)


_ROLES = {9: 'window', 10: 'client', 34: 'list item', 33: 'list',
          43: 'static text', 42: 'text', 44: 'push button',
          45: 'check box', 46: 'radio button', 56: 'menu item',
          57: 'menu bar', 22: 'tool bar', 41: 'title bar'}


def _role_name(role):
    try:
        return _ROLES.get(int(role), '')
    except Exception:
        return ''


def _join(*parts):
    return ', '.join(part.strip() for part in parts if part and part.strip())


def open_reader():
    """Whatever this guest can be read with. Never raises."""
    system = platform.system().lower()
    tiers = {'windows': WindowsReader, 'linux': AtspiReader,
             'darwin': MacReader}
    build = tiers.get(system)
    if build is None:
        found = NoReader()
        found.why = 'no accessibility layer is written for %s' % (
            platform.system() or 'this system')
        return found
    try:
        return build()
    except Exception as error:
        found = NoReader()
        found.why = '%s could not be read: %s' % (platform.system(), error)
        return found


# --------------------------------------------------------------------------- #
# Getting it to the host
# --------------------------------------------------------------------------- #
class RpcToolLink(object):
    """VMware Tools' own channel. No port, no address, no firewall.

    The variable holds what it was last set to for ever, so the same words
    twice would be read once - which is wrong for a pointer that comes back
    to a control it was on a moment ago. A counter in front of the value is
    what makes a repeat a new value, and the reader takes it off again.
    """

    kind = 'rpctool'

    #: Where VMware Tools puts its own tool, per platform. Looked for on
    #: PATH first, because a guest may have it anywhere.
    PLACES = (
        r'C:\Program Files\VMware\VMware Tools\vmware-rpctool.exe',
        r'C:\Program Files (x86)\VMware\VMware Tools\vmware-rpctool.exe',
        '/usr/bin/vmware-rpctool',
        '/usr/sbin/vmware-rpctool',
        '/Library/Application Support/VMware Tools/vmware-rpctool',
    )

    def __init__(self, variable=SAY_VAR):
        self.variable = variable
        self.tool = self._find()
        self.sent = 0
        self.failed = 0
        self.counter = 0

    @classmethod
    def _find(cls):
        found = shutil.which('vmware-rpctool')
        if found:
            return found
        for guess in cls.PLACES:
            if os.path.isfile(guess):
                return guess
        return ''

    def ready(self):
        return bool(self.tool)

    def why(self):
        return ('vmware-rpctool was not found - VMware Tools is not '
                'installed in this guest')

    def send(self, kind, said, rect=None):
        if not self.tool:
            self.failed += 1
            return False
        self.counter += 1
        value = '%d|%s|%s' % (self.counter, kind, said)
        try:
            done = subprocess.run(
                [self.tool, 'info-set %s %s' % (self.variable, value)],
                capture_output=True, timeout=5)
        except Exception:
            self.failed += 1
            return False
        if done.returncode != 0:
            self.failed += 1
            return False
        self.sent += 1
        return True

    def report(self):
        return 'rpctool %s, sent %d, failed %d' % (
            self.tool or 'missing', self.sent, self.failed)


class TcpLink(object):
    """One line of JSON per thing seen. Reconnects by itself."""

    kind = 'tcp'

    def __init__(self, host, port, token):
        self.where = (host, int(port))
        self.token = token
        self.sock = None
        self.sent = 0
        self.failed = 0

    def ready(self):
        return bool(self.where[0] and self.token)

    def why(self):
        return 'the reader\'s address and key are both needed for --transport tcp'

    def send(self, kind, said, rect=None):
        line = json.dumps({'token': self.token, 'kind': kind,
                           'say': said, 'rect': rect or []},
                          ensure_ascii=False) + '\n'
        for attempt in (1, 2):
            try:
                if self.sock is None:
                    self.sock = socket.create_connection(self.where, timeout=4)
                self.sock.sendall(line.encode('utf-8'))
                self.sent += 1
                return True
            except OSError:
                self.failed += 1
                try:
                    if self.sock is not None:
                        self.sock.close()
                except OSError:
                    pass
                self.sock = None
                if attempt == 2:
                    return False
        return False

    def report(self):
        return 'tcp %s:%d, sent %d, failed %d' % (
            self.where[0], self.where[1], self.sent, self.failed)


def open_link(args):
    """The transport asked for, or the one that is really available."""
    if args.transport in ('rpctool', 'auto'):
        link = RpcToolLink(args.variable)
        if link.ready():
            return link
        if args.transport == 'rpctool':
            return link
    return TcpLink(args.host, args.port, args.token)


# --------------------------------------------------------------------------- #
def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Tell the reader on the host what this guest shows.')
    parser.add_argument('--transport', default='auto',
                        choices=('auto', 'rpctool', 'tcp'),
                        help='auto prefers VMware Tools, which needs no '
                             'network at all')
    parser.add_argument('--host', default='',
                        help="the host's address, for --transport tcp")
    parser.add_argument('--port', type=int, default=37375)
    parser.add_argument('--token', default='',
                        help="the key from the reader's settings page")
    parser.add_argument('--variable', default=SAY_VAR,
                        help='the guest variable to set (rpctool)')
    parser.add_argument('--interval', type=float, default=0.2,
                        help='seconds between looks (default 0.2)')
    parser.add_argument('--no-pointer', action='store_true',
                        help='do not follow the pointer')
    parser.add_argument('--no-focus', action='store_true',
                        help='do not follow the keyboard')
    parser.add_argument('--once', action='store_true',
                        help='report once and stop - for checking the link')
    args = parser.parse_args(argv)

    reader = open_reader()
    if isinstance(reader, NoReader):
        print('agent: %s' % reader.why)
        print('agent: read this guest as a picture from the host instead - '
              'that needs nothing in here.')
        return 2
    link = open_link(args)
    if not link.ready():
        print('agent: %s' % link.why())
        return 2
    print('agent: reading with %s, sending over %s'
          % (type(reader).__name__, link.kind))

    was_pointer = was_focus = ''
    while True:
        if not args.no_pointer:
            where = None
            try:
                where = reader.pointer()
            except Exception:
                where = None
            if where:
                said = reader.at_point(where[0], where[1])
                # Only what CHANGED: a pointer resting on a control is not
                # news, and the reader would drop it anyway.
                if said and said != was_pointer:
                    was_pointer = said
                    link.send('pointer', said)
        if not args.no_focus:
            said = ''
            try:
                said = reader.focused()
            except Exception:
                said = ''
            if said and said != was_focus:
                was_focus = said
                link.send('focus', said)
        if args.once:
            print('agent: %s' % link.report())
            return 0 if link.sent else 1
        time.sleep(max(0.05, args.interval))


if __name__ == '__main__':
    sys.exit(main())
