# -*- coding: utf-8 -*-
"""The two things a sighted person sees without looking at anything.

A program that has stopped answering shows an hourglass. A program that
wants you shows a flashing button on the taskbar. Neither is a control,
neither is in any accessibility tree, and no screen reader says either -
so a blind user's experience of both is the same: nothing happens. They
press the key again, or they never find out that the chat window had
something to say.

Both are readable, and neither costs anything worth counting.

**Busy is the mouse cursor.** ``GetCursorInfo`` says which cursor is being
shown and Windows' wait and app-starting cursors are shared handles, so it
is the same identity test :mod:`dialog_kind` uses for the message-box
icons - two numbers, no picture. It is polled, because there is no event
for it; the call is a few microseconds and the poll is slow.

**Attention is the shell hook.** ``RegisterShellHookWindow`` is how the
taskbar itself is told, and ``HSHELL_FLASH`` is Windows saying "this window
called FlashWindowEx" - which is exactly what a program does when it wants
the user. Titan's own shell already lives on this hook; here it is used for
the one message a reader wants from it.

**The trap, which Titan has already paid for once:** Windows keeps the
ADDRESS of the window procedure, and a ctypes callback that Python has
collected is freed memory the next message calls into. So the callback is
held for as long as the window exists, and the window is destroyed before
the callback is let go. Titan's shell documents this as its most frequent
hard crash; there is no reason to learn it twice.

Off is one switch each, and every failure - no user32, a shell hook that
will not register, a window class that will not create - stands the layer
down with a reason rather than raising anywhere near the reader.
"""

import ctypes
import threading
import time

from . import i18n

_ = i18n.install(globals())

#: Windows' own cursors. Shared for the life of the session, which is what
#: makes comparing the handles exact.
IDC_WAIT = 32514
IDC_APPSTARTING = 32650

#: How long the hourglass must last before it is worth saying. A program
#: that is busy for a fifth of a second is a program that is working, and
#: announcing that would be a reader talking over every keystroke.
BUSY_AFTER = 0.6

#: How often the cursor is looked at. `GetCursorInfo` is a few
#: microseconds; this is slow because nothing here is urgent, and because a
#: thread that wakes four times a second is a thread nobody notices.
BUSY_POLL = 0.25

#: The shell's own message numbers.
HSHELL_FLASH = 0x8006

_LOCK = threading.RLock()
_state = {'busy': False, 'since': 0.0, 'said': 0, 'attention': 0,
          'why': '', 'running': False}


def report():
    with _LOCK:
        return dict(_state)


def _user32():
    try:
        return ctypes.windll.user32
    except Exception:                                # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# The hourglass
# --------------------------------------------------------------------------- #
class _CURSORINFO(ctypes.Structure):
    _fields_ = [('cbSize', ctypes.c_uint32),
                ('flags', ctypes.c_uint32),
                ('hCursor', ctypes.c_void_p),
                ('ptScreenPos_x', ctypes.c_long),
                ('ptScreenPos_y', ctypes.c_long)]


_wait_cursors = set()


def _busy_cursors():
    if _wait_cursors:
        return _wait_cursors
    user32 = _user32()
    if user32 is None:
        return _wait_cursors
    try:
        user32.LoadCursorW.restype = ctypes.c_void_p
        for number in (IDC_WAIT, IDC_APPSTARTING):
            # The integer carried IN a pointer - `MAKEINTRESOURCE`. As a
            # `c_wchar_p` ctypes refuses it; as a bare int it is a 32-bit
            # argument where a 64-bit one belongs.
            handle = int(user32.LoadCursorW(None,
                                            ctypes.c_void_p(number)) or 0)
            if handle:
                _wait_cursors.add(handle)
    except Exception:                                # noqa: BLE001
        pass
    return _wait_cursors


def cursor_is_busy():
    """Whether Windows is showing an hourglass right now."""
    user32 = _user32()
    if user32 is None:
        return False
    info = _CURSORINFO()
    info.cbSize = ctypes.sizeof(_CURSORINFO)
    try:
        if not user32.GetCursorInfo(ctypes.byref(info)):
            return False
    except Exception:                                # noqa: BLE001
        return False
    return int(info.hCursor or 0) in _busy_cursors()


def busy_wanted():
    from . import configSpec
    return bool(configSpec.read().get('busyState', True))


def _say(text, interrupt=False):
    from . import compat
    if compat.queueHandler is None or compat.ui is None:
        return
    def speak():
        try:
            compat.ui.message(text)
        except Exception:                            # noqa: BLE001
            pass
    compat.queueHandler.queueFunction(compat.queueHandler.eventQueue, speak)


_stop = threading.Event()
_thread = None


def _watch():
    """One slow loop, watching the cursor. Says nothing most of the time."""
    while not _stop.wait(BUSY_POLL):
        if not busy_wanted():
            continue
        try:
            busy = cursor_is_busy()
        except Exception:                            # noqa: BLE001
            continue
        with _LOCK:
            was = _state['busy']
            if busy and not was:
                _state['busy'] = True
                _state['since'] = time.time()
                continue
            if busy and was:
                if _state['since'] and \
                        (time.time() - _state['since']) >= BUSY_AFTER:
                    _state['since'] = 0.0
                    _state['said'] += 1
                    said = True
                else:
                    said = False
                if not said:
                    continue
                # Translators: said when the program shows an hourglass.
                text = _('busy')
            else:
                if not was:
                    continue
                _state['busy'] = False
                if _state['since']:
                    # It never lasted long enough to be announced, so there
                    # is nothing to say it has finished.
                    _state['since'] = 0.0
                    continue
                _state['since'] = 0.0
                # Translators: said when the program has stopped being busy.
                text = _('ready')
        _say(text)
        _cue('busy' if text == _('busy') else 'ready')


def _cue(which):
    """Titan's own sound for it, when Titan is there. Silent when not."""
    try:
        from . import earcons
        earcons.play_named({'busy': 'ellipses.ogg',
                            'ready': 'clicked.ogg'}.get(which, ''))
    except Exception:                                # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# "Requires attention"
# --------------------------------------------------------------------------- #
_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint,
                              ctypes.c_void_p, ctypes.c_void_p) \
    if hasattr(ctypes, 'WINFUNCTYPE') else None

#: Held for as long as the window exists. Windows keeps the ADDRESS of the
#: procedure, so a callback Python has collected is freed memory the next
#: message calls into - which is a crash with no traceback, and the one
#: Titan's own shell hit hardest.
_held = {'proc': None, 'hwnd': 0, 'message': 0, 'class': None}


def attention_wanted():
    from . import configSpec
    return bool(configSpec.read().get('attentionState', True))


def _window_title(hwnd):
    user32 = _user32()
    if user32 is None or not hwnd:
        return ''
    try:
        length = int(user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd)) or 0)
        if length <= 0:
            return ''
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(ctypes.c_void_p(hwnd), buffer, length + 1)
        return str(buffer.value or '').strip()
    except Exception:                                # noqa: BLE001
        return ''


def _flashed(hwnd):
    with _LOCK:
        _state['attention'] += 1
    title = _window_title(hwnd)
    # Translators: said when a window asks for the user's attention (its
    # taskbar button is flashing). {what} is the window's title.
    text = _('{what} requires attention').format(
        what=title or _('a window'))
    _say(text)
    try:
        from . import earcons
        earcons.play_named('notification.ogg')
    except Exception:                                # noqa: BLE001
        pass


def _shell_loop():
    """A message-only window on a thread of its own, on the shell hook."""
    user32 = _user32()
    if user32 is None:
        with _LOCK:
            _state['why'] = 'there is no user32 on this machine'
        return

    def procedure(hwnd, message, wparam, lparam):
        try:
            if message and message == _held['message'] \
                    and int(wparam or 0) == HSHELL_FLASH:
                if attention_wanted():
                    _flashed(int(lparam or 0))
        except Exception:                            # noqa: BLE001
            pass
        return int(user32.DefWindowProcW(ctypes.c_void_p(hwnd), message,
                                         ctypes.c_void_p(wparam),
                                         ctypes.c_void_p(lparam)))

    if _WNDPROC is None:
        with _LOCK:
            _state['why'] = 'this Python has no stdcall callbacks'
        return
    _held['proc'] = _WNDPROC(procedure)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [('style', ctypes.c_uint), ('lpfnWndProc', _WNDPROC),
                    ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                    ('hInstance', ctypes.c_void_p), ('hIcon', ctypes.c_void_p),
                    ('hCursor', ctypes.c_void_p),
                    ('hbrBackground', ctypes.c_void_p),
                    ('lpszMenuName', ctypes.c_wchar_p),
                    ('lpszClassName', ctypes.c_wchar_p)]

    name = 'TitanEnhancementsShellHook'
    wanted = WNDCLASS()
    wanted.lpfnWndProc = _held['proc']
    wanted.lpszClassName = name
    try:
        wanted.hInstance = ctypes.c_void_p(
            ctypes.windll.kernel32.GetModuleHandleW(None))
    except Exception:                                # noqa: BLE001
        wanted.hInstance = None
    _held['class'] = wanted
    try:
        if not user32.RegisterClassW(ctypes.byref(wanted)):
            raise OSError(ctypes.get_last_error() if hasattr(ctypes, 'get_last_error') else 0)
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _state['why'] = 'the window class would not register: %s' % error
        return
    try:
        user32.CreateWindowExW.restype = ctypes.c_void_p
        # **`hInstance` must go back as a POINTER.** Reading it off
        # the class structure gives a plain Python int, and a module
        # handle is too large for the C int ctypes converts a bare int
        # into: `CreateWindowExW` raises `OverflowError: int too long
        # to convert` before Windows is ever called. Caught by driving
        # the real thing - both windows here failed at creation, which
        # each module then reported as "the window would not be
        # created" and nobody would have known why.
        hwnd = int(user32.CreateWindowExW(
            0, ctypes.c_wchar_p(name), ctypes.c_wchar_p(name), 0, 0, 0, 0, 0,
            ctypes.c_void_p(-3),  # HWND_MESSAGE
            None, ctypes.c_void_p(wanted.hInstance), None) or 0)
    except Exception as error:                       # noqa: BLE001
        with _LOCK:
            _state['why'] = 'the window would not be created: %s' % error
        return
    if not hwnd:
        with _LOCK:
            _state['why'] = 'the window would not be created'
        return
    _held['hwnd'] = hwnd
    try:
        _held['message'] = int(user32.RegisterWindowMessageW(
            ctypes.c_wchar_p('SHELLHOOK')) or 0)
        registered = bool(user32.RegisterShellHookWindow(ctypes.c_void_p(hwnd)))
    except Exception as error:                       # noqa: BLE001
        registered = False
        with _LOCK:
            _state['why'] = 'the shell hook refused: %s' % error
    if not registered:
        with _LOCK:
            if not _state['why']:
                _state['why'] = 'the shell hook refused this window'
        _destroy()
        return
    with _LOCK:
        _state['running'] = True
        _state['why'] = ''

    class MSG(ctypes.Structure):
        _fields_ = [('hwnd', ctypes.c_void_p), ('message', ctypes.c_uint),
                    ('wParam', ctypes.c_void_p), ('lParam', ctypes.c_void_p),
                    ('time', ctypes.c_uint), ('pt_x', ctypes.c_long),
                    ('pt_y', ctypes.c_long)]
    message = MSG()
    while True:
        got = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
        if got in (0, -1):
            break
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
    _destroy()


def _destroy():
    user32 = _user32()
    hwnd = _held.get('hwnd') or 0
    if user32 is not None and hwnd:
        try:
            user32.DeregisterShellHookWindow(ctypes.c_void_p(hwnd))
        except Exception:                            # noqa: BLE001
            pass
        try:
            user32.DestroyWindow(ctypes.c_void_p(hwnd))
        except Exception:                            # noqa: BLE001
            pass
    _held['hwnd'] = 0
    # Only now may the callback go: Windows holds its address until the
    # window it belongs to is really gone.
    _held['proc'] = None
    _held['class'] = None
    with _LOCK:
        _state['running'] = False


_shell_thread = None


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
def start():
    """Both watchers, each only if it is wanted. Never raises."""
    global _thread, _shell_thread
    _stop.clear()
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_watch, name='TitanBusyWatch',
                                   daemon=True)
        _thread.start()
    if attention_wanted() and (_shell_thread is None
                               or not _shell_thread.is_alive()):
        _shell_thread = threading.Thread(target=_shell_loop,
                                         name='TitanAttentionWatch',
                                         daemon=True)
        _shell_thread.start()
    return True


def stop():
    """Put everything back. The window goes before its callback does."""
    _stop.set()
    user32 = _user32()
    hwnd = _held.get('hwnd') or 0
    if user32 is not None and hwnd:
        try:
            # WM_CLOSE, so the loop leaves through its own exit and the
            # teardown happens on the thread that owns the window.
            user32.PostMessageW(ctypes.c_void_p(hwnd), 0x0010, 0, 0)
        except Exception:                            # noqa: BLE001
            pass
    return True
