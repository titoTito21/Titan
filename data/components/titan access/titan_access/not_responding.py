# -*- coding: utf-8 -*-
"""The window in front has stopped answering: say so, once, and stop
asking it things.

NVDA stutters in front of a hung program - it goes on asking the window
for its focus, its text and its caret, every one of those calls waits out
a timeout, and what the user hears is a reader that cuts in and out. A
sighted person sees "(Not Responding)" in the title bar; a blind one
should HEAR it, once, and then not be made to wait on the program.

So this watches the foreground window from a thread of its own, twice a
second, using only calls that never send the window a message - Windows'
own verdict (`IsHungAppWindow`, true once a program has not taken a
message for five seconds) and its title (`InternalGetWindowText`, read
from Windows' own copy) - so asking cannot itself be what gets stuck.
When Windows replaces a frozen window with its "ghost" stand-in, the ghost
is traced back to the real window (`HungWindowFromGhostWindow`).

On the way into a hung window it says "Brak odpowiedzi w <title>"
(protected, so nothing cuts it) and sets `engine.hung_hwnd`, which the
focus path reads to leave that window alone. When the program answers
again, or another window comes to the front, it is forgotten - and coming
back to a window that is still hung says it again, because that is news
to somebody who left it.
"""

import sys
import threading

try:
    from .log import log
except Exception:                                    # noqa: BLE001
    def log(message):
        print(message)

POLL_S = 0.5
GHOST_CLASS = 'Ghost'


def _user32():
    if not sys.platform.startswith('win'):
        return None
    import ctypes
    return ctypes.windll.user32


def window_title(hwnd):
    """The title Windows keeps for ``hwnd`` - no message sent."""
    user32 = _user32()
    if user32 is None or not hwnd:
        return ''
    import ctypes
    buffer = ctypes.create_unicode_buffer(512)
    try:
        user32.InternalGetWindowText(ctypes.c_void_p(int(hwnd)), buffer, 512)
    except Exception:                                # noqa: BLE001
        return ''
    return buffer.value.strip()


def window_class(hwnd):
    user32 = _user32()
    if user32 is None or not hwnd:
        return ''
    import ctypes
    buffer = ctypes.create_unicode_buffer(128)
    try:
        user32.GetClassNameW(ctypes.c_void_p(int(hwnd)), buffer, 128)
    except Exception:                                # noqa: BLE001
        return ''
    return buffer.value


def hung_window_in_front():
    """``(hwnd, title)`` of the foreground window when Windows says it is
    not responding, else ``(0, '')``."""
    user32 = _user32()
    if user32 is None:
        return 0, ''
    import ctypes
    try:
        front = int(user32.GetForegroundWindow() or 0)
    except Exception:                                # noqa: BLE001
        return 0, ''
    if not front:
        return 0, ''
    if window_class(front) == GHOST_CLASS:
        real = 0
        try:
            finder = user32.HungWindowFromGhostWindow
            finder.restype = ctypes.c_void_p
            real = int(finder(ctypes.c_void_p(front)) or 0)
        except Exception:                            # noqa: BLE001
            real = 0
        return (real or front), window_title(real or front)
    try:
        hung = bool(user32.IsHungAppWindow(ctypes.c_void_p(front)))
    except Exception:                                # noqa: BLE001
        hung = False
    return (front, window_title(front)) if hung else (0, '')


def sentence(title):
    """What is said: "Brak odpowiedzi w <title>"."""
    from .localization import L
    title = str(title or '').strip()
    # Windows itself may have added "(Not Responding)" to the title; the
    # sentence already says it.
    for suffix in ('(Brak odpowiedzi)', '(Nie odpowiada)',
                   '(Not Responding)'):
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()
    return L('engine.notResponding', title) if title \
        else L('engine.notRespondingNoTitle')


class Watch(object):
    """The foreground window, watched for not answering."""

    def __init__(self, engine, poll=POLL_S, probe=None):
        self.engine = engine
        self.poll = poll
        self.probe = probe or hung_window_in_front
        self.announced = 0
        self.said = 0
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if not sys.platform.startswith('win') and self.probe is \
                hung_window_in_front:
            return self
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name='TitanAccessNotResponding')
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(self.poll):
            try:
                self.check_once()
            except Exception as error:               # noqa: BLE001
                log('[TitanAccess] not-responding watch: %s' % error)

    def check_once(self):
        """One look at the window in front. True when it was announced."""
        hwnd, title = self.probe()
        if not hwnd:
            if self.announced:
                self.announced = 0
            if getattr(self.engine, 'hung_hwnd', 0):
                self.engine.hung_hwnd = 0
            return False
        self.engine.hung_hwnd = hwnd
        self.engine.hung_title = title
        if hwnd == self.announced:
            return False
        self.announced = hwnd
        self.said += 1
        log('[TitanAccess] not responding: %r' % title)
        speech = getattr(self.engine, 'speech', None)
        if speech is not None:
            try:
                speech.speak(sentence(title), interrupt=True, protected=True)
            except TypeError:
                speech.speak(sentence(title), interrupt=True)
        return True


def belongs_to(hwnd, hung):
    """Whether ``hwnd`` is ``hung`` or a window inside it."""
    if not hwnd or not hung:
        return False
    if int(hwnd) == int(hung):
        return True
    user32 = _user32()
    if user32 is None:
        return False
    import ctypes
    try:
        getter = user32.GetAncestor
        getter.restype = ctypes.c_void_p
        root = int(getter(ctypes.c_void_p(int(hwnd)), 2) or 0)   # GA_ROOT
        return root == int(hung)
    except Exception:                                # noqa: BLE001
        return False
